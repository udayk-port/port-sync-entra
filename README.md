# Microsoft Entra ID to Port.io Group Synchronization

A secure Python script that automatically synchronizes Microsoft Entra ID (formerly Azure AD) group members to Port.io by sending user invites. This tool is designed for organizations using both Microsoft 365 and Port.io for developer portal management.

## 🎯 Overview

This script bridges the gap between Microsoft Entra ID group management and Port.io user access by:

1. **Reading group information** from CLI arguments, environment variables, or Azure DevOps webhooks
2. **Authenticating with Microsoft Graph API** using client credentials
3. **Finding Microsoft Entra ID groups** by display name with secure OData queries
4. **Fetching transitive members** (including nested groups)
5. **Extracting user emails** from group members
6. **Sending invites to Port.io** for each user with optional role and team assignments

## 🚀 Quick Start

### Prerequisites

- **Python 3.7+** with pip
- **Microsoft Entra ID App Registration** with Graph API permissions
- **Port.io API Token** with user invitation permissions
- **Required Python packages**: `requests`, `msal`

### Installation

1. **Clone or download the script**:
   ```bash
   git clone https://github.com/udayk-port/port-sync-entra
   cd port-sync-entra
   ```

2. **Install dependencies**:
   ```bash
   pip install requests msal
   ```

3. **Set up environment variables** (see [Configuration](#configuration) section)

4. **Run the script**:
   ```bash
   python sync_group_to_port.py --group "Your Group Name" --verbose
   ```

## ⚙️ Configuration

### Required Environment Variables

Set these environment variables with your Microsoft Entra ID and Port.io credentials:

```bash
# Microsoft Entra ID Configuration
export GRAPH_TENANT_ID="your-tenant-id"           # Microsoft Entra ID tenant ID
export GRAPH_CLIENT_ID="your-client-id"           # App registration client ID
export GRAPH_CLIENT_SECRET="your-client-secret"   # App registration client secret

# Port.io Configuration
export PORT_API_TOKEN="your-port-token"           # Port.io API token
```

### Optional Environment Variables

```bash
# Group Configuration
export GROUP_NAME="Default Group Name"            # Default group to sync

# Port.io Invite Configuration
export PORT_NOTIFY="true"                         # Send invite emails (true/false)
export PORT_ROLE="developer"                      # Role to assign to invitees
export PORT_TEAM_IDS="team1,team2,team3"         # Comma-separated team IDs

# Operational Configuration
export DRY_RUN="false"                            # Test mode without sending invites
export WEBHOOK_PAYLOAD_PATH="/path/to/payload.json"  # Webhook payload file path
```

### Microsoft Entra ID App Registration Setup

1. **Create an App Registration** in Microsoft Entra ID:
   - Go to Azure Portal → Microsoft Entra ID → App registrations
   - Click "New registration"
   - Name: "Port.io Group Sync"
   - Account types: "Accounts in this organizational directory only"

2. **Grant API Permissions**:
   - Go to "API permissions" → "Add a permission"
   - Select "Microsoft Graph" → "Application permissions"
   - Add these permissions:
     - `Group.Read.All` (Read all groups)
     - `User.Read.All` (Read all users)
   - Click "Grant admin consent"

3. **Create Client Secret**:
   - Go to "Certificates & secrets" → "New client secret"
   - Description: "Port.io Group Sync Secret"
   - Expires: Choose appropriate duration
   - Copy the secret value (you won't see it again)

4. **Get Tenant ID**:
   - Go to Microsoft Entra ID → Overview
   - Copy the "Tenant ID"

### Port.io API Token Setup

1. **Generate API Token**:
   - Log into your Port.io organization
   - Go to Settings → API → Generate Token
   - Name: "Group Sync Script"
   - Permissions: Select "User Management" or "Admin" permissions
   - Copy the generated token

## 📖 Usage

### Command Line Interface

```bash
python sync_group_to_port.py [OPTIONS]
```

#### Options

- `--group GROUP_NAME`: Specify the Microsoft Entra ID group display name to sync
- `--verbose`: Enable verbose logging for debugging

#### Examples

**Basic usage with CLI argument**:
```bash
python sync_group_to_port.py --group "Engineering Team" --verbose
```

**Using environment variable**:
```bash
export GROUP_NAME="Security Team"
python sync_group_to_port.py --verbose
```

**Dry run mode (test without sending invites)**:
```bash
export DRY_RUN="true"
python sync_group_to_port.py --group "Test Group" --verbose
```

**With role and team assignments**:
```bash
export PORT_ROLE="developer"
export PORT_TEAM_IDS="team1,team2"
python sync_group_to_port.py --group "Development Team" --verbose
```

### Azure DevOps Webhook Integration

The script can be triggered by Azure DevOps webhooks:

**Via stdin**:
```bash
echo '{"group": "My Group Name"}' | python sync_group_to_port.py
```

**Via file**:
```bash
export WEBHOOK_PAYLOAD_PATH="/path/to/webhook-payload.json"
python sync_group_to_port.py
```

**Webhook payload format**:
```json
{
  "group": "Group Display Name",
  "resource": {
    "groupName": "Alternative Group Name"
  },
  "data": {
    "group": "Another Group Name"
  }
}
```

## 🔧 Advanced Configuration

### Group Name Resolution Priority

The script resolves group names in this order:
1. **CLI argument** (`--group`)
2. **Environment variable** (`GROUP_NAME`)
3. **Webhook payload** (from file or stdin)

### Port.io Invite Configuration

#### Role Assignment
```bash
export PORT_ROLE="developer"  # Assign specific role to all invitees
```

#### Team Assignment
```bash
export PORT_TEAM_IDS="team1,team2,team3"  # Assign to multiple teams
```

#### Notification Control
```bash
export PORT_NOTIFY="false"  # Disable invite emails (users won't receive email notifications)
```

### Error Handling and Retry Logic

The script includes robust error handling:

- **Environment Variable Validation**: Clear error messages when required variables are missing
- **File Reading Errors**: Graceful handling of webhook payload reading issues
- **API Failures**: Continues processing other users if individual invites fail
- **Invalid Groups**: Exits with clear error message if group not found
- **Network Issues**: Comprehensive request exception handling with 30-second timeouts
- **Rate Limiting**: Includes 50ms delay between API calls
- **Email Validation**: Proper format validation to prevent invalid emails

## 📊 Output and Logging

### Verbose Mode Output

When using `--verbose`, the script provides detailed progress information:

```
Resolving group 'Engineering Team'…
Found group: Engineering Team (12345-67890-abcdef)
Will invite 25 users…
[1/25] user1@company.com: OK - invited
[2/25] user2@company.com: OK - skipped (409) User already exists
[3/25] user3@company.com: ERR - 400 Bad Request
...
Done. Invited OK: 23, failed: 2
```

### Exit Codes

- **0**: Success (all users processed successfully)
- **2**: Partial failure (some users failed to invite)
- **1**: Fatal error (script could not complete)

### Log Levels

- **Standard Output**: Progress updates and results
- **Standard Error**: Warnings, errors, and verbose debugging information

## 🛡️ Security Features

### Input Validation and Sanitization

The script includes comprehensive security measures:

- **OData Injection Prevention**: Proper input sanitization for Microsoft Graph queries
- **URL Encoding**: Safe parameter encoding for API requests
- **Character Filtering**: Blocks dangerous characters in group names
- **Error Message Sanitization**: Prevents sensitive information leakage
- **Email Format Validation**: Regex-based validation to ensure valid email addresses
- **Environment Variable Validation**: Clear error messages for missing required variables

### Recent Security Enhancements

The script has been enhanced with additional security and robustness features:

- **Enhanced Error Handling**: Comprehensive validation of environment variables and file operations
- **Network Resilience**: Improved timeout handling and request exception management
- **Input Validation**: Enhanced email format validation using regex patterns
- **Graceful Degradation**: Better handling of webhook payload reading errors

### Authentication Security

- **Client Credentials Flow**: Uses Microsoft Entra ID app registration for secure authentication
- **Token Management**: Automatic token acquisition and refresh
- **Environment Variables**: Secure storage of credentials
- **No Hardcoded Secrets**: All sensitive data comes from environment variables

### API Security

- **HTTPS Only**: All API calls use secure HTTPS connections
- **Bearer Token Authentication**: Secure authentication with Port.io
- **Request Timeouts**: Prevents hanging requests
- **Rate Limiting**: Gentle API usage to avoid rate limits

## 🔍 Troubleshooting

### Common Issues

#### 1. Authentication Failures

**Error**: `Failed to acquire Graph token`

**Solutions**:
- Verify `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, and `GRAPH_CLIENT_SECRET`
- Check that the app registration has the required permissions
- Ensure admin consent has been granted for the permissions
- Verify the client secret hasn't expired

#### 2. Group Not Found

**Error**: `Group not found: [group name]`

**Solutions**:
- Verify the group display name is correct
- Check that the app registration has `Group.Read.All` permission
- Ensure the group exists in the specified Microsoft Entra ID tenant
- Try using the exact group display name (case-sensitive)

#### 3. Port.io API Errors

**Error**: `400 Bad Request` or `401 Unauthorized`

**Solutions**:
- Verify the `PORT_API_TOKEN` is valid and not expired
- Check that the token has user invitation permissions
- Ensure the Port.io organization is accessible
- Verify the role and team IDs are valid

#### 4. User Email Issues

**Warning**: `Skipping user without email`

**Solutions**:
- Check that users have valid email addresses in Microsoft Entra ID
- Verify the `mail` or `userPrincipalName` fields are populated
- Ensure the app registration has `User.Read.All` permission

#### 5. Environment Variable Issues

**Error**: `Required environment variable [VARIABLE_NAME] is not set`

**Solutions**:
- Verify all required environment variables are set: `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, `PORT_API_TOKEN`
- Check that environment variables are exported in your shell session
- Ensure variable names are spelled correctly (case-sensitive)

#### 6. Webhook Payload Issues

**Warning**: `Could not read webhook payload: [error]`

**Solutions**:
- Verify the webhook payload file exists and is readable
- Check that the payload file contains valid JSON
- Ensure the `WEBHOOK_PAYLOAD_PATH` environment variable points to the correct file
- For stdin input, ensure valid JSON is being piped to the script

### Debug Mode

Enable verbose logging to troubleshoot issues:

```bash
python sync_group_to_port.py --group "Your Group" --verbose
```

### Dry Run Mode

Test the script without sending actual invites:

```bash
export DRY_RUN="true"
python sync_group_to_port.py --group "Your Group" --verbose
```

## 🚀 Integration Examples

### Azure DevOps Pipeline

```yaml
# azure-pipelines.yml
trigger:
  branches:
    include:
    - main

pool:
  vmImage: 'ubuntu-latest'

steps:
- task: PythonScript@0
  inputs:
    scriptSource: 'filePath'
    scriptPath: 'sync_group_to_port.py'
    arguments: '--group "Engineering Team" --verbose'
  env:
    GRAPH_TENANT_ID: $(GRAPH_TENANT_ID)
    GRAPH_CLIENT_ID: $(GRAPH_CLIENT_ID)
    GRAPH_CLIENT_SECRET: $(GRAPH_CLIENT_SECRET)
    PORT_API_TOKEN: $(PORT_API_TOKEN)
    PORT_ROLE: 'developer'
    PORT_TEAM_IDS: 'team1,team2'
```

### Scheduled Sync with Cron

```bash
# Add to crontab for daily sync at 9 AM
0 9 * * * cd /path/to/port-sync-entra && python sync_group_to_port.py --group "Engineering Team" >> /var/log/port-sync.log 2>&1
```

### Docker Container

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY sync_group_to_port.py .
RUN pip install requests msal

CMD ["python", "sync_group_to_port.py"]
```

```bash
# Run with environment variables
docker run -e GRAPH_TENANT_ID=xxx -e GRAPH_CLIENT_ID=xxx -e GRAPH_CLIENT_SECRET=xxx -e PORT_API_TOKEN=xxx -e GROUP_NAME="Engineering Team" port-sync-entra
```

## 📋 API Reference

### Microsoft Graph API Endpoints

- **Group Search**: `GET /groups?$filter=displayName eq 'group_name'`
- **Transitive Members**: `GET /groups/{id}/transitiveMembers`
- **User Details**: `GET /users/{id}`

### Port.io API Endpoints

- **User Invite**: `POST /v1/users/invite`

### Request/Response Examples

#### Microsoft Graph Group Search
```http
GET https://graph.microsoft.com/v1.0/groups?$select=id,displayName&$filter=displayName eq 'Engineering Team'&$top=5
Authorization: Bearer {access_token}
```

#### Port.io User Invite
```http
POST https://api.port.io/v1/users/invite
Authorization: Bearer {port_token}
Content-Type: application/json

{
  "invitee": {
    "email": "user@company.com",
    "role": "developer",
    "teamIds": ["team1", "team2"]
  },
  "notify": true
}
```

## 🤝 Contributing

### Development Setup

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/new-feature`
3. **Install development dependencies**: `pip install -r requirements-dev.txt`
4. **Make your changes**
5. **Run tests**: `python -m pytest tests/`
6. **Submit a pull request**

### Code Style

- Follow PEP 8 style guidelines
- Use type hints for function parameters and return values
- Include docstrings for all functions
- Add comments for complex logic

### Testing

```bash
# Run unit tests
python -m pytest tests/

# Run with coverage
python -m pytest --cov=sync_group_to_port tests/

# Run linting
flake8 sync_group_to_port.py
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

### Getting Help

1. **Check the troubleshooting section** above
2. **Review the verbose output** for detailed error information
3. **Test with dry run mode** to isolate issues
4. **Verify your configuration** against the setup instructions

### Reporting Issues

When reporting issues, please include:

- Python version
- Operating system
- Verbose output from the script
- Configuration (without sensitive values)
- Steps to reproduce the issue

### Feature Requests

We welcome feature requests! Please open an issue with:

- Clear description of the desired feature
- Use case and motivation
- Proposed implementation approach (if applicable)


**Ready to sync your Microsoft Entra ID groups with Port.io?** Start with the [Quick Start](#-quick-start) guide and follow the configuration steps! 🚀
