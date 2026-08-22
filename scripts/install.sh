#!/usr/bin/env bash
# MediaHub Setup — one-line installer (macOS + Linux).
#
# Interactive (open the web wizard yourself afterwards):
#   curl -fsSL https://raw.githubusercontent.com/dhouchin1/mediahub-setup/main/scripts/install.sh | bash
#
# Fully automated (bootstrap, then run a headless install in one shot):
#   curl -fsSL .../scripts/install.sh | bash -s -- install --role seedbox --config seedbox.yml --yes
#
# What it does:
#   1. Detects macOS or Linux and verifies Python 3.12+
#   2. Installs pipx if needed (Homebrew / apt / dnf / pip --user)
#   3. pipx-installs (or upgrades) mediahub-setup into its own venv
#   4. (Linux, opt-in) installs Docker Engine when MEDIAHUB_INSTALL_DOCKER=1
#   5. If extra args were passed, runs `mediahub-setup <args>`; else prints the
#      "run the wizard" prompt.

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; BLD='\033[1m'; RST='\033[0m'
info()  { printf "${GRN}✔${RST}  %s\n" "$*"; }
step()  { printf "${BLD}→${RST}  %s\n" "$*"; }
warn()  { printf "${YLW}⚠${RST}  %s\n" "$*"; }
die()   { printf "${RED}✘  %s${RST}\n" "$*" >&2; exit 1; }

echo ""
printf "${BLD}MediaHub Setup installer${RST}\n"
echo "──────────────────────────────"
echo ""

# ── sudo helper (no-op when already root) ────────────────────────────────────
SUDO=""
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  command -v sudo &>/dev/null && SUDO="sudo"
fi

OS="$(uname -s)"

# ── Package-manager install helper (Linux) ───────────────────────────────────
linux_pkg_install() {
  if command -v apt-get &>/dev/null; then
    $SUDO apt-get update -y && $SUDO apt-get install -y "$@"
  elif command -v dnf &>/dev/null; then
    $SUDO dnf install -y "$@"
  elif command -v yum &>/dev/null; then
    $SUDO yum install -y "$@"
  elif command -v pacman &>/dev/null; then
    $SUDO pacman -Sy --noconfirm "$@"
  else
    return 1
  fi
}

# ── Ensure Python 3.12+ ──────────────────────────────────────────────────────
ensure_python() {
  if ! command -v python3 &>/dev/null; then
    if [[ "$OS" == "Linux" ]]; then
      step "Installing Python 3…"
      linux_pkg_install python3 python3-venv python3-pip || die "Could not install Python 3 automatically. Install Python 3.12+ and re-run."
    else
      die "Python 3 not found. Run: brew install python@3.12"
    fi
  fi

  read -r PYVER_MAJOR PYVER_MINOR < <(
    python3 -c 'import sys; print(sys.version_info.major, sys.version_info.minor)'
  )
  if [[ "$PYVER_MAJOR" -lt 3 || ( "$PYVER_MAJOR" -eq 3 && "$PYVER_MINOR" -lt 12 ) ]]; then
    if [[ "$OS" == "Darwin" ]]; then
      die "Python 3.12+ required (found ${PYVER_MAJOR}.${PYVER_MINOR}). Run: brew install python@3.12"
    fi
    die "Python 3.12+ required (found ${PYVER_MAJOR}.${PYVER_MINOR}). On Ubuntu: 'sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt-get install python3.12'."
  fi
  info "Python ${PYVER_MAJOR}.${PYVER_MINOR} detected."
}

# ── Ensure pipx ──────────────────────────────────────────────────────────────
ensure_pipx() {
  if command -v pipx &>/dev/null; then return 0; fi
  warn "pipx not found — installing…"
  if [[ "$OS" == "Darwin" ]] && command -v brew &>/dev/null; then
    step "brew install pipx"; brew install pipx
  elif [[ "$OS" == "Linux" ]] && linux_pkg_install pipx; then
    : # installed from the distro
  else
    step "pip install --user pipx"
    python3 -m pip install --user pipx
  fi
  python3 -m pipx ensurepath || true
  export PATH="$HOME/.local/bin:$PATH"
  command -v pipx &>/dev/null || python3 -m pipx --version &>/dev/null || die "pipx install failed."
  info "pipx installed."
}

pipx_run() { command -v pipx &>/dev/null && pipx "$@" || python3 -m pipx "$@"; }

# ── Optional: Docker Engine on Linux (opt-in) ────────────────────────────────
ensure_docker() {
  if command -v docker &>/dev/null; then info "Docker detected."; return 0; fi
  if [[ "$OS" == "Linux" && "${MEDIAHUB_INSTALL_DOCKER:-0}" == "1" ]]; then
    step "Installing Docker Engine (get.docker.com)…"
    curl -fsSL https://get.docker.com | $SUDO sh
    $SUDO usermod -aG docker "$(id -un)" || true
    warn "Added you to the 'docker' group — log out/in (or run 'newgrp docker') for it to take effect."
  else
    warn "Docker not found. Install it first: https://docs.docker.com/engine/install/"
    # Plain `[[ ... ]] && warn` as the last command makes this function
    # return 1 on macOS, and under `set -e` that aborted the whole script
    # before mediahub-setup was ever installed. Use an explicit if.
    if [[ "$OS" == "Linux" ]]; then
      warn "  (or re-run with MEDIAHUB_INSTALL_DOCKER=1 to auto-install Docker Engine)"
    fi
  fi
  return 0
}

# ── Run ──────────────────────────────────────────────────────────────────────
ensure_python
ensure_pipx
ensure_docker

if pipx_run list 2>/dev/null | grep -q "mediahub-setup"; then
  step "Upgrading mediahub-setup…"; pipx_run upgrade mediahub-setup
else
  step "Installing mediahub-setup…"; pipx_run install mediahub-setup
fi
export PATH="$HOME/.local/bin:$PATH"

echo ""
printf "${GRN}${BLD}Installation complete!${RST}\n"
echo ""

# ── Pass-through: run `mediahub-setup <args>` when args were supplied ─────────
if [[ "$#" -gt 0 ]]; then
  if ! command -v mediahub-setup &>/dev/null; then
    die "mediahub-setup is not on PATH. Run 'pipx ensurepath', open a new shell, then: mediahub-setup $*"
  fi
  step "Running: mediahub-setup $*"
  echo ""
  exec mediahub-setup "$@"
fi

echo "  Start the wizard:"
echo ""
printf "    ${BLD}mediahub-setup${RST}\n"
echo ""
echo "  Or run a headless install (e.g. a remote seedbox):"
echo ""
printf "    ${BLD}mediahub-setup install --role seedbox --config seedbox.yml${RST}\n"
echo ""

if ! command -v mediahub-setup &>/dev/null; then
  warn "mediahub-setup is not yet on your PATH."
  echo "  Run this once, then open a new terminal:"
  echo ""
  echo "    pipx ensurepath"
  echo ""
fi
