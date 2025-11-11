# Security Policy

## Overview

Claude CLI Cloud is a web-based interface for managing Claude CLI sessions across multiple remote machines. This document outlines security best practices for deploying and using this application.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.14.x  | :white_check_mark: |
| < 2.14  | :x:                |

## Security Best Practices

### 1. API Key Management

**NEVER** commit API keys to version control. Always use environment variables:

```bash
# Set your Anthropic API key
export ANTHROPIC_API_KEY="your-api-key-here"

# Add to your shell profile for persistence
echo 'export ANTHROPIC_API_KEY="your-key-here"' >> ~/.bashrc
```

**Files that should NEVER be committed:**
- `.env` and `.env.*` files
- Any file containing API keys, tokens, or passwords
- Private key files (`*.key`, `*.pem`)
- Credential files (`*credentials*`, `*secret*`)

### 2. Configuration Files

The following files contain sensitive data and are automatically excluded via `.gitignore`:

- `connections.json` - Contains server IP addresses and connection details
- `preferences.json` - User preferences and settings
- `server-config.json` - Server configuration
- `conversations.db` - Conversation history database

**These files should remain local and never be pushed to public repositories.**

### 3. Git Exclusions Feature

When using the "Push to Git" feature, always configure Git Exclusions for your projects:

1. Go to **Projects** tab
2. Click **Edit** on your project
3. Use the **"Use Defaults"** button in the Git Exclusions field
4. Customize as needed for your project

**Default exclusions include:**
- Dependencies (`node_modules/`, `venv/`, `env/`)
- Secrets (`.env`, `*.key`, `*.pem`, `*credentials*`)
- Databases (`*.db`, `*.sqlite`, `conversations.db`)
- Logs (`*.log`, `bridge.log`)
- Build artifacts (`dist/`, `build/`, `__pycache__/`)
- IDE files (`.vscode/`, `.idea/`)

### 4. GitHub Token Security

When using GitHub integration:

1. **Use Personal Access Tokens (PAT)** with minimal required permissions
2. **Never hardcode tokens** in project configurations
3. **Revoke tokens** immediately if exposed
4. **Use fine-grained tokens** when possible (read/write access only to specific repos)

**To create a GitHub token:**
- Go to: https://github.com/settings/tokens
- Click "Generate new token (classic)"
- Select only required scopes (typically just `repo`)
- Set an expiration date
- Store securely

### 5. Network Security

**WebSocket Connections:**
- Use firewall rules to restrict WebSocket access to trusted IPs
- Consider using Tailscale or VPN for secure remote access
- Default ports: 8765 (proxy), 8766 (terminal server)

**HTTP APIs:**
- Conversation API: Port 8889
- Connections API: Port 8887
- Settings API: Port 8888
- Consider using HTTPS in production

### 6. Database Security

The `conversations.db` SQLite database stores:
- Session metadata and conversation history
- Project assignments
- Favorite sessions
- Custom titles

**Protection measures:**
- Excluded from git via `.gitignore`
- File permissions: `chmod 600 conversations.db`
- Located in project root (not web-accessible)
- Backup regularly to secure location

### 7. Deployment Security

When deploying to production:

1. **Change default ports** if exposed to the internet
2. **Use environment variables** for all sensitive configuration
3. **Enable HTTPS** for web interface
4. **Restrict CORS** origins in server configurations
5. **Use process managers** (systemd, pm2) instead of running servers directly
6. **Set up log rotation** to prevent disk space issues
7. **Regular security updates** for dependencies

### 8. Access Control

**Multi-machine Setup:**
- Each machine should have its own connection configuration
- Use SSH keys for remote machine access
- Implement network-level access controls (firewall, VPN)
- Consider using authentication middleware for web interface

## Reporting Security Vulnerabilities

If you discover a security vulnerability, please report it responsibly:

1. **DO NOT** create a public GitHub issue
2. Email the project maintainer directly
3. Include detailed steps to reproduce
4. Allow reasonable time for a fix before public disclosure

## Security Checklist for Going Public

Before making your repository public:

- [ ] Remove all hardcoded API keys and tokens
- [ ] Verify `.gitignore` excludes sensitive files
- [ ] Check git history for accidentally committed secrets
- [ ] Use `git log --all --full-history -- *secret* *token* *.env` to search history
- [ ] Update README with security warnings
- [ ] Review all configuration examples use placeholders
- [ ] Remove any internal IP addresses or hostnames from examples
- [ ] Configure Git Exclusions for all projects

## Security Features Built-In

### Automatic File Exclusions

The application automatically excludes large files (>20MB) when pushing to git to prevent:
- Accidentally committing large binary files
- Repository bloat
- Slow push operations

### Comment Support in Git Exclusions

Git exclusion lists support comments (lines starting with `#`) for better organization:

```gitignore
# Secrets & Credentials
.env
*.key
*.pem

# Build outputs
dist/
build/
```

### Safe Defaults

The application ships with secure defaults:
- No hardcoded credentials
- Comprehensive `.gitignore`
- Environment variable requirements
- Local-first configuration

## Resources

- [GitHub Security Best Practices](https://docs.github.com/en/code-security)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Anthropic API Key Management](https://docs.anthropic.com/claude/reference/api-keys)

## License

This security policy is part of the Claude CLI Cloud project and follows the same license as the main project.

---

**Last Updated:** November 11, 2025
**Version:** 2.14.2
