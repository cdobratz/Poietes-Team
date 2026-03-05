#!/usr/bin/env bash
# scripts/setup.sh — First-time environment setup

set -euo pipefail

echo "=== OpenHands Agent Team — Setup ==="

# 1. Python version check
python_version=$(python3 --version 2>&1 | awk '{print $2}')
required="3.10"
if ! python3 -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)"; then
  echo "❌ Python 3.10+ required (found $python_version)"
  exit 1
fi
echo "✅ Python $python_version"

# 2. Install Python deps
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt --quiet

# 3. Install security tools
echo "🔒 Installing security tools..."
pip install bandit safety pip-audit --quiet

# 4. Install Playwright browsers (optional)
if command -v playwright &>/dev/null; then
  echo "🎭 Installing Playwright browsers..."
  playwright install chromium --with-deps || true
fi

# 5. Copy config examples if not present
if [ ! -f config/settings.yaml ]; then
  cp config/settings.example.yaml config/settings.yaml
  echo "📋 Created config/settings.yaml — please fill in your API keys"
fi
if [ ! -f config/projects.yaml ]; then
  cp config/projects.example.yaml config/projects.yaml
  echo "📋 Created config/projects.yaml — add your projects"
fi

# 6. Create .env template
if [ ! -f .env ]; then
  cat > .env << 'EOF'
ANTHROPIC_API_KEY=your_anthropic_key_here
XAI_API_KEY=
GITHUB_TOKEN=
GITLAB_TOKEN=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
MEM0_API_KEY=
MINIMAX_API_KEY=
EOF
  echo "🔑 Created .env — fill in your API keys"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit config/settings.yaml   — set LLM backend and integrations"
echo "  2. Edit config/projects.yaml   — add your projects"
echo "  3. Edit .env                   — add API keys"
echo "  4. python main.py validate     — check your config"
echo "  5. python main.py run --task 'scan all projects'"
