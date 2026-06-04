#!/usr/bin/env bash
set -e
echo "╔══════════════════════════════════════════╗"
echo "║       GAMEBOOK STUDIO — Setup            ║"
echo "╚══════════════════════════════════════════╝"

PY=$(command -v python3.11 || command -v python3 || echo "")
if [ -z "$PY" ]; then echo "ERROR: Python 3.11+ required"; exit 1; fi
echo "Python: $($PY --version)"

echo "Installing dependencies..."
$PY -m pip install --upgrade pip --quiet 2>/dev/null
$PY -m pip install arcade Pillow --quiet 2>/dev/null
echo "  Done"

echo "Generating textures..."
$PY texture_gen.py
echo "  Done"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║         Launching Gamebook Studio        ║"
echo "╚══════════════════════════════════════════╝"
echo "F=Fullscreen  H=Help  ESC=Back  Space=Skip text"
echo ""
$PY main.py
