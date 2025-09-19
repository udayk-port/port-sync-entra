#!/usr/bin/env python3
"""
Sync Microsoft Entra ID (formerly Azure AD) group members to Port by sending user invites.

What this script does
------------
1) Reads a group name from CLI arg or env GROUP_NAME (fallback parses an Azure DevOps webhook payload if provided via stdin/ENV).
2) Uses Microsoft Graph (client credentials) to find the group by displayName and fetch *transitive* members.
3) Collects user emails (prefers `mail`, falls back to `userPrincipalName`).
4) Calls Port's "Invite a user to your organization" API for each email.

Environment variables (mark these as Azure Pipelines secrets)
-------------------------------------------------------------
- GRAPH_TENANT_ID        : Microsoft Entra ID tenant ID
- GRAPH_CLIENT_ID        : App (client) ID with Graph application permissions
- GRAPH_CLIENT_SECRET    : App (client) secret
- PORT_API_TOKEN         : Port API token (Bearer)
- GROUP_NAME             : (optional) name of the group to sync
- PORT_NOTIFY            : (optional) "true"/"false"; default true (whether Port sends invite emails)
- PORT_ROLE              : (optional) Port role ID/slug to include in invitee payload (if your org requires it)
- PORT_TEAM_IDS          : (optional) comma-separated team IDs to assign on invite
- DRY_RUN                : (optional) "true" to print, not call Port API

CLI usage
---------
    python sync_group_to_port.py --group "My Group Name" --verbose

Exit codes
----------
0 on success; non-zero on fatal error.

Notes
-----
- Uses transitive members API so nested groups are expanded.
- Skips objects that are not users (service principals/devices/etc.).
- Idempotent-ish: if Port returns validation or already-exists errors, we log and continue.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import requests

try:
    import msal  # type: ignore
except Exception:
    print("msal not installed. In Azure Pipelines, add a step: `pip install msal`", file=sys.stderr)
    raise

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
PORT_BASE = "https://api.port.io"

@dataclass
class Config:
    tenant_id: str
    client_id: str
    client_secret: str
    port_token: str
    group_name: str
    notify: bool = True
    role: Optional[str] = None
    team_ids: Optional[List[str]] = None
    dry_run: bool = False
    verbose: bool = False


def env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y"}


def get_required_env(key: str) -> str:
    """Get required environment variable with clear error message."""
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"Required environment variable {key} is not set")
    return value


def build_config(args: argparse.Namespace) -> Config:
    # Group name priority: CLI > ENV > webhook payload (if present via file/stdin)
    group_name = args.group or os.getenv("GROUP_NAME")
    if not group_name:
        # Try to parse webhook payload from Azure DevOps: either ADO passes JSON body into a file path env
        # or we read stdin if something is piped.
        payload_path = os.getenv("WEBHOOK_PAYLOAD_PATH")
        payload = None
        if payload_path and os.path.exists(payload_path):
            try:
                with open(payload_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not read webhook payload: {e}", file=sys.stderr)
                payload = None
        else:
            try:
                if not sys.stdin.isatty():
                    payload = json.load(sys.stdin)
            except Exception:
                payload = None
        if payload:
            # Adjust this to your Port → Azure DevOps webhook schema
            group_name = (
                payload.get("resource", {}).get("groupName")
                or payload.get("data", {}).get("group")
                or payload.get("group")
            )
    if not group_name:
        raise SystemExit("Group name not provided. Use --group or set GROUP_NAME env or provide it in the webhook payload.")

    cfg = Config(
        tenant_id=get_required_env("GRAPH_TENANT_ID"),
        client_id=get_required_env("GRAPH_CLIENT_ID"),
        client_secret=get_required_env("GRAPH_CLIENT_SECRET"),
        port_token=get_required_env("PORT_API_TOKEN"),
        group_name=group_name,
        notify=env_bool("PORT_NOTIFY", True),
        role=os.getenv("PORT_ROLE"),
        team_ids=[s.strip() for s in os.getenv("PORT_TEAM_IDS", "").split(",") if s.strip()] or None,
        dry_run=env_bool("DRY_RUN", False),
        verbose=args.verbose,
    )
    return cfg


def get_graph_token(cfg: Config) -> str:
    app = msal.ConfidentialClientApplication(
        cfg.client_id,
        authority=f"https://login.microsoftonline.com/{cfg.tenant_id}",
        client_credential=cfg.client_secret,
    )
    scope = ["https://graph.microsoft.com/.default"]
    result = app.acquire_token_silent(scope, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=scope)
    if "access_token" not in result:
        raise SystemExit(f"Failed to acquire Graph token: {result}")
    return result["access_token"]


def sanitize_odata_string(value: str) -> str:
    """
    Properly sanitize a string for use in OData queries.
    
    This function handles:
    - Single quote escaping (required by OData)
    - URL encoding for special characters
    - Prevention of OData injection attacks
    
    Args:
        value: The string to sanitize
        
    Returns:
        Properly sanitized string safe for OData queries
    """
    if not value:
        return ""
    
    # First, escape single quotes (OData requirement)
    # Single quotes must be doubled in OData string literals
    escaped = value.replace("'", "''")
    
    # Additional validation: check for potentially dangerous OData syntax
    # This prevents injection of OData operators, functions, etc.
    dangerous_patterns = [
        r'[;,]',  # OData separators
        r'\(',    # Function calls
        r'\)',    # Function calls
        r'/',     # Path separators
        r'\\',    # Escape sequences
        r'\$',    # OData system query options
        r'@',     # OData annotations
        r'#',     # OData type annotations
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, escaped):
            raise ValueError(f"Group name contains potentially dangerous characters: {value}")
    
    return escaped


def build_odata_filter(property_name: str, operator: str, value: str) -> str:
    """
    Build a safe OData filter expression.
    
    Args:
        property_name: The property to filter on (e.g., 'displayName')
        operator: The OData operator (e.g., 'eq', 'startswith')
        value: The value to compare against
        
    Returns:
        Safe OData filter expression
    """
    # Validate property name (should be alphanumeric with underscores)
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', property_name):
        raise ValueError(f"Invalid property name: {property_name}")
    
    # Validate operator (common OData operators)
    valid_operators = {'eq', 'ne', 'gt', 'ge', 'lt', 'le', 'startswith', 'endswith', 'contains'}
    if operator not in valid_operators:
        raise ValueError(f"Invalid OData operator: {operator}")
    
    # Sanitize the value
    sanitized_value = sanitize_odata_string(value)
    
    if operator in {'startswith', 'endswith', 'contains'}:
        return f"{operator}({property_name},'{sanitized_value}')"
    else:
        return f"{property_name} {operator} '{sanitized_value}'"


def graph_request(token: str, method: str, url: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    # For $count with $filter or $search (if used), Graph sometimes needs ConsistencyLevel
    if "$count=true" in url or "$search=" in url:
        headers.setdefault("ConsistencyLevel", "eventual")
    
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        if 200 <= resp.status_code < 300:
            return resp.json()
        raise RuntimeError(f"Graph {method} {url} failed: {resp.status_code} {resp.text}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Network error during Graph request: {e}")


def find_group_id(token: str, group_name: str) -> Tuple[str, str]:
    """Find a group by displayName with proper OData sanitization.
    Prefer exact match; fallback to startswith.
    Returns (group_id, displayName).
    """
    try:
        # Build safe OData filter for exact match
        exact_filter = build_odata_filter("displayName", "eq", group_name)
        
        # Construct URL with proper encoding
        query_params = {
            "$select": "id,displayName",
            "$filter": exact_filter,
            "$top": "5"
        }
        
        # URL encode the query parameters
        encoded_params = urllib.parse.urlencode(query_params)
        url = f"{GRAPH_BASE}/groups?{encoded_params}"
        
        data = graph_request(token, "GET", url)
        items = data.get("value", [])
        
        if not items:
            # Try startswith fallback with proper sanitization
            startswith_filter = build_odata_filter("displayName", "startswith", group_name)
            
            query_params = {
                "$select": "id,displayName", 
                "$filter": startswith_filter,
                "$top": "5"
            }
            
            encoded_params = urllib.parse.urlencode(query_params)
            url = f"{GRAPH_BASE}/groups?{encoded_params}"
            
            data = graph_request(token, "GET", url)
            items = data.get("value", [])
        
        if not items:
            raise SystemExit(f"Group not found: {group_name}")
        
        if len(items) > 1:
            print("Warning: multiple groups matched; using the first. Matches:", file=sys.stderr)
            for g in items:
                print(f"  - {g.get('displayName')} ({g.get('id')})", file=sys.stderr)
        
        g = items[0]
        return g["id"], g.get("displayName", group_name)
        
    except ValueError as e:
        raise SystemExit(f"Invalid group name: {e}")
    except Exception as e:
        raise SystemExit(f"Error finding group: {e}")


def iter_transitive_user_members(token: str, group_id: str) -> Iterable[dict]:
    # We only want user objects; Graph returns different object types
    url = f"{GRAPH_BASE}/groups/{group_id}/transitiveMembers?$select=id,displayName,mail,userPrincipalName,userType,oDataType&$top=999"
    while True:
        data = graph_request(token, "GET", url)
        for obj in data.get("value", []):
            # Filter to user objects (oDataType can be '#microsoft.graph.user')
            if obj.get("@odata.type") == "#microsoft.graph.user" or obj.get("oDataType") == "#microsoft.graph.user":
                yield obj
        next_link = data.get("@odata.nextLink")
        if not next_link:
            break
        url = next_link


def extract_email(u: dict) -> Optional[str]:
    email = (u.get("mail") or u.get("userPrincipalName") or "").strip()
    if not email or "@" not in email:
        return None
    
    # Basic email format validation
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return None
    
    return email


def port_invite(cfg: Config, email: str) -> Tuple[bool, str]:
    """Send invite via Port API. Returns (ok, message)."""
    if cfg.dry_run:
        return True, "DRY_RUN: not sending"
    url = f"{PORT_BASE}/v1/users/invite"
    headers = {
        "Authorization": f"Bearer {cfg.port_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {"invitee": {"email": email}, "notify": cfg.notify}
    if cfg.role:
        body["invitee"]["role"] = cfg.role
    if cfg.team_ids:
        body["invitee"]["teamIds"] = cfg.team_ids
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code in (200, 201, 202):
        return True, "invited"
    # tolerate validation/idempotency errors
    if resp.status_code in (409, 422):
        return True, f"skipped ({resp.status_code}) {resp.text[:160]}"
    return False, f"{resp.status_code} {resp.text}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Invite all users from a Microsoft Entra ID group to Port")
    ap.add_argument("--group", dest="group", help="Group displayName to sync")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cfg = build_config(args)
    if cfg.verbose:
        print(f"Resolving group '{cfg.group_name}'…", file=sys.stderr)
    token = get_graph_token(cfg)
    gid, gname = find_group_id(token, cfg.group_name)
    if cfg.verbose:
        print(f"Found group: {gname} ({gid})", file=sys.stderr)

    users = []
    for u in iter_transitive_user_members(token, gid):
        email = extract_email(u)
        if email:
            users.append(email)
        elif cfg.verbose:
            print(f"Skipping user without email: {u.get('displayName')}", file=sys.stderr)

    unique_emails = sorted(set(users))
    if cfg.verbose:
        print(f"Will invite {len(unique_emails)} users…", file=sys.stderr)

    ok_count = 0
    fail_count = 0
    for i, email in enumerate(unique_emails, start=1):
        ok, msg = port_invite(cfg, email)
        status = "OK" if ok else "ERR"
        print(f"[{i}/{len(unique_emails)}] {email}: {status} - {msg}")
        if ok:
            ok_count += 1
        else:
            fail_count += 1
        # small throttle to be gentle
        time.sleep(0.05)

    print(f"Done. Invited OK: {ok_count}, failed: {fail_count}")
    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
