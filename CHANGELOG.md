# Claude CLI Cloud - Changelog

## Version 2.13.0 - 2025-11-09

### New Features
- **Git Push History Viewer**: Added "📜 History" button to view push logs
  - Shows last 50 git push attempts with timestamps
  - Displays commit messages and success/failure status
  - Includes full git output for debugging
  - Color-coded status indicators (green for success, red for failure)
  - Automatically saves history for each push

### Enhancements
- **GitHub Token Storage**: Projects can now store GitHub Personal Access Tokens
  - Added GitHub Token field to project create/edit modals
  - Tokens are automatically used for authentication during git push
  - Secure password field input for tokens
  - Per-project token configuration

### Technical Details
- Added `push_history` array to project data structure
- Push history limited to last 50 entries per project
- History includes: timestamp, success status, commit message, git output
- Bridge server now returns commit_message in git_push_result

---

## Version 2.12.0 - 2025-11-09

### New Features
- **Simple Git Push Integration**: Added "Push to Git" button to project cards
  - Manual one-click push to commit and push all changes
  - Auto-generated commit messages with timestamps (format: "Auto-save YYYY-MM-DD HH:MM:SS")
  - Proper error handling and loading states
  - Works with existing git repositories and credentials

### Technical Details
- Added `git_push_auto` WebSocket handler in bridge server
- Button shows "⏳ Pushing..." during operation
- Handles "nothing to commit" case gracefully
- Validates WebSocket connection before attempting push

---

## Version 2.11.13 - 2025-11-07

### Fixes
- **Install script now auto-configures hooks**: `install-bridge.sh` now automatically sets up conversation hooks in `~/.claude/settings.json`
- Added hostname mapping for CM Webserver AWS instance (ip-172-26-13-164)
- Fixed CM Webserver bridge configuration and machine name

### What's New
- Install script is now fully automated - no manual hook configuration needed
- All new bridge server installations will have conversation sync enabled by default

---

## Version 2.11.12 - 2025-11-07

### New Features
- **Auto-tag Local CLI sessions with hostname**: When running Claude CLI directly (not through bridge), sessions are now automatically tagged with the server hostname instead of generic "Local CLI"
  - Recycle server: "Recycle Server"
  - Steel server: "Steel Server"  
  - CM Webserver: "CM Webserver"
  - Unknown hosts: "{hostname} (Local CLI)"

### Fixes
- Fixed hooks configuration format on Recycle server (array of objects with hooks array)
- Sessions now properly differentiate between servers in conversation history

### API Additions
- `/api/conversations/query?session_id=XXX` - Check if specific session exists in central database
- `/api/conversations/stats` - Get conversation statistics grouped by connection

### New Tools
- `check-remote-sync.sh` - Script to verify if conversations are syncing to central server

---

## Version 2.11.11 - 2025-11-07
- Central conversation sync via settings-api port 8891
- Conversation hooks send to central server for aggregation

## Version 2.6 - 2025-11-06
- MCP config moved from init script to install script
- Init script optimized for faster connection times
