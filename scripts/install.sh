#!/usr/bin/env bash
# MediaHub Setup — one-line installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/dhouchin/mediahub-setup/main/scripts/install.sh | bash
#
# What it does:
#   1. Verifies macOS + Python 3.12+
#   2. Installs pipx if needed (via Homebrew or pip)
#   3. pipx-installs (or upgrades) mediahub-setup
#   4. Prints the "run it" prompt
#
# Nothing is installed system-wide — pipx keeps mediahub-setup in its
# own isolated virtual environment at ~/.local/pipx/venvs/mediahub-setup.

set -euo pipefail

# ── Colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLD='\033[1m'
RST='\033[0m'

info()  { printf "${GRN}✔${RST}  %s\n"      "$*"; }
step()  { printf "${BLD}→${RST}  %s\n"      "$*"; }
warn()  { printf "${YLW}⚠${RST}  %s\n"      "$*"; }
die()   { printf "${RED}✘  %s${RST}\n" "$*" >&2; exit 1; }

echo ""
printf "${BLD}MediaHub Setup installer${RST}\n"
echo "──────────────────────────────"
echo ""

# ── Platform check ─────────────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
  die "mediahub-setup requires macOS. Linux support is planned."
fi

# ── Python version check ────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  die "Python 3 is not installed. Run: brew install python@3.12"
fi

read -r PYVER_MAJOR PYVER_MINOR < <(
  python3 -c 'import sys; print(sys.version_info.major, sys.version_info.minor)'
)

if [[ "$PYVER_MAJOR" -lt 3 || ("$PYVER_MAJOR" -eq 3 && "$PYVER_MINOR" -lt 12) ]]; then
  die "Python 3.12+ required (found ${PYVER_MAJOR}.${PYVER_MINOR}). Run: brew install python@3.12"
fi

info "Python ${PYVER_MAJOR}.${PYVER_MINOR} detected."

# ── pipx ───────────────────────────────────────────────────────────────────
if ! command -v pipx &>/dev/null; then
  warn "pipx not found — installing..."
  if command -v brew &>/dev/null; then
    step "brew install pipx"
    brew install pipx
    pipx ensurepath
  else
    step "pip install --user pipx"
    python3 -m pip install --user pipx
    python3 -m pipx ensurepath
  fi
  info "pipx installed."
fi

# ── mediahub-setup ─────────────────────────────────────────────────────────
if pipx list 2>/dev/null | grep -q "mediahub-setup"; then
  step "Upgrading mediahub-setup..."
  pipx upgrade mediahub-setup
else
  step "Installing mediahub-setup..."
  pipx install mediahub-setup
fi

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
printf "${GRN}${BLD}Installation complete!${RST}\n"
echo ""
echo "  Start the wizard:"
echo ""
printf "    ${BLD}mediahub-setup${RST}\n"
echo ""
echo "  Your browser will open automatically."
echo ""

# Remind about PATH if pipx was just installed
if ! command -v mediahub-setup &>/dev/null; then
  warn "mediahub-setup is not yet on your PATH."
  echo "  Run this once, then open a new terminal:"
  echo ""
  echo "    pipx ensurepath"
  echo ""
fi
