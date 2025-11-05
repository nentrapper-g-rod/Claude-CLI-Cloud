#!/bin/bash
# Test Setup Script for Remote Claude CLI Chat
# This script validates your installation is ready to run

echo "================================================"
echo "Remote Claude CLI Chat - Setup Validator"
echo "================================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

# Check Python version
echo "1. Checking Python version..."
if command -v python3 &> /dev/null; then
    PY_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    PY_MAJOR=$(echo $PY_VERSION | cut -d. -f1)
    PY_MINOR=$(echo $PY_VERSION | cut -d. -f2)

    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 7 ]; then
        echo -e "   ${GREEN}✓${NC} Python $PY_VERSION found"
    else
        echo -e "   ${RED}✗${NC} Python 3.7+ required, found $PY_VERSION"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "   ${RED}✗${NC} Python 3 not found"
    ERRORS=$((ERRORS + 1))
fi

# Check Python modules
echo ""
echo "2. Checking Python dependencies..."

check_module() {
    if python3 -c "import $1" 2>/dev/null; then
        echo -e "   ${GREEN}✓${NC} $1 installed"
    else
        echo -e "   ${RED}✗${NC} $1 missing - run: pip3 install $1"
        ERRORS=$((ERRORS + 1))
    fi
}

check_module "websockets"
check_module "anthropic"
check_module "aiofiles"

# Check API key
echo ""
echo "3. Checking Anthropic API key..."
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo -e "   ${YELLOW}⚠${NC} ANTHROPIC_API_KEY not set"
    echo "   Set it with: export ANTHROPIC_API_KEY='your-key-here'"
    WARNINGS=$((WARNINGS + 1))
else
    KEY_LEN=${#ANTHROPIC_API_KEY}
    if [ "$KEY_LEN" -lt 10 ]; then
        echo -e "   ${RED}✗${NC} API key seems too short"
        ERRORS=$((ERRORS + 1))
    else
        echo -e "   ${GREEN}✓${NC} API key is set (${KEY_LEN} characters)"
    fi
fi

# Check files exist
echo ""
echo "4. Checking required files..."

check_file() {
    if [ -f "$1" ]; then
        SIZE=$(ls -lh "$1" | awk '{print $5}')
        echo -e "   ${GREEN}✓${NC} $1 ($SIZE)"
    else
        echo -e "   ${RED}✗${NC} $1 missing"
        ERRORS=$((ERRORS + 1))
    fi
}

check_file "claude-bridge-server.py"
check_file "index.html"
check_file "README.md"
check_file "QUICKSTART.md"

# Check Claude CLI home (optional)
echo ""
echo "5. Checking Claude CLI installation (optional)..."
if [ -d "$HOME/.claude" ]; then
    echo -e "   ${GREEN}✓${NC} Claude CLI home found at ~/.claude"

    # Check for projects
    if [ -d "$HOME/.claude/projects" ]; then
        PROJECT_COUNT=$(ls -1 "$HOME/.claude/projects" 2>/dev/null | wc -l)
        echo -e "   ${GREEN}✓${NC} Found $PROJECT_COUNT project(s)"
    fi

    # Check for history
    if [ -f "$HOME/.claude/history.jsonl" ]; then
        HISTORY_SIZE=$(ls -lh "$HOME/.claude/history.jsonl" | awk '{print $5}')
        echo -e "   ${GREEN}✓${NC} History file found ($HISTORY_SIZE)"
    fi
else
    echo -e "   ${YELLOW}⚠${NC} Claude CLI not installed"
    echo "   This is OK - you can still use the system"
    echo "   Sessions won't be discovered from existing Claude CLI usage"
    WARNINGS=$((WARNINGS + 1))
fi

# Check network/firewall (basic)
echo ""
echo "6. Checking network readiness..."
if command -v netstat &> /dev/null; then
    if netstat -an 2>/dev/null | grep -q ":8765"; then
        echo -e "   ${YELLOW}⚠${NC} Port 8765 already in use"
        echo "   You may need to use a different port with --port argument"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "   ${GREEN}✓${NC} Port 8765 available"
    fi
else
    echo -e "   ${YELLOW}⚠${NC} Cannot check port availability (netstat not found)"
    WARNINGS=$((WARNINGS + 1))
fi

# Summary
echo ""
echo "================================================"
echo "Summary"
echo "================================================"

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed! You're ready to go!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. python3 claude-bridge-server.py --machine-name 'My Computer'"
    echo "  2. Open index.html in your browser"
    echo ""
    echo "See QUICKSTART.md for detailed instructions"
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠ Setup OK with $WARNINGS warning(s)${NC}"
    echo ""
    echo "You can proceed, but check the warnings above"
else
    echo -e "${RED}✗ Found $ERRORS error(s) and $WARNINGS warning(s)${NC}"
    echo ""
    echo "Please fix the errors above before proceeding"
    echo ""
    echo "Quick fixes:"
    echo "  - Install dependencies: pip3 install websockets anthropic aiofiles"
    echo "  - Set API key: export ANTHROPIC_API_KEY='your-key-here'"
fi

echo ""
exit $ERRORS
