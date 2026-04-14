#!/bin/bash
# ── Job Alert Bot Launcher ────────────────────────────────────────────────────
# Usage:  ./run.sh YOUR_BOT_TOKEN YOUR_CHAT_ID
# Or:     TELEGRAM_TOKEN=xxx TELEGRAM_CHAT_ID=yyy ./run.sh

set -e
cd "$(dirname "$0")"

if [ -n "$1" ]; then export TELEGRAM_TOKEN="$1"; fi
if [ -n "$2" ]; then export TELEGRAM_CHAT_ID="$2"; fi

if [ -z "$TELEGRAM_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
  echo ""
  echo "  Usage: ./run.sh <BOT_TOKEN> <CHAT_ID>"
  echo ""
  echo "  Get these from:"
  echo "    Token   → Telegram @BotFather → /newbot"
  echo "    Chat ID → Telegram @userinfobot → send any message"
  echo ""
  exit 1
fi

echo "Starting Job Alert Bot..."
./venv/bin/python3 bot.py
