#!/bin/bash
# Setup Git Push Credentials for Claude CLI Cloud
# This script helps configure git credentials for the Push to Git feature

echo "==============================================="
echo "  Git Push Setup for Claude CLI Cloud"
echo "==============================================="
echo ""
echo "You need a GitHub Personal Access Token to push."
echo ""
echo "To create one:"
echo "1. Go to: https://github.com/settings/tokens"
echo "2. Click 'Generate new token (classic)'"
echo "3. Give it repo permissions"
echo "4. Copy the token"
echo ""

read -p "Enter your GitHub username: " GITHUB_USER
read -sp "Enter your GitHub Personal Access Token: " GITHUB_TOKEN
echo ""

# Create credentials file
echo "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com" > ~/.git-credentials
chmod 600 ~/.git-credentials

# Configure git to use stored credentials
git config --global credential.helper store

echo ""
echo "✓ Credentials configured!"
echo ""
echo "Testing git push..."
cd /opt/Claude-CLI-Cloud
git push -u origin master

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ Git push successful!"
    echo "✓ The 'Push to Git' button will now work automatically"
else
    echo ""
    echo "✗ Git push failed. Please check your token and try again."
fi
