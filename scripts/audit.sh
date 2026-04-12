#!/usr/bin/env bash
set -euo pipefail

# -------------------------------
# Colors
# -------------------------------

GREEN="\033[1;32m"
RED="\033[1;31m"
BLUE="\033[1;34m"
YELLOW="\033[1;33m"
RESET="\033[0m"

# -------------------------------
# Defaults
# -------------------------------

MODE="light"

# -------------------------------
# Help
# -------------------------------

usage() {
cat <<EOF
Usage: $(basename "$0") [--deep] [-h]

Audit script for codira project.

Modes:
(default)        Light scan:
- Semgrep with public rules (deterministic, fast)
- pip-audit on Poetry dependencies

--deep           Deep scan:
- Semgrep full scan (auto / cloud rules)
- may require SEMGREP_APP_TOKEN
- slower, broader coverage

Options:
-h, --help       Show this help message

Requirements:

* poetry installed and project environment set up
* uv (uvx) available in PATH

Notes:

* Light mode is deterministic and CI-friendly
* Deep mode uses Semgrep registry (network + optional auth)
EOF
  }

# -------------------------------
# Parse args
# -------------------------------

for arg in "$@"; do
case "$arg" in
--deep) MODE="deep" ;;
-h|--help) usage; exit 0 ;;
*)
echo -e "${RED}[!] Unknown argument: $arg${RESET}"
usage
exit 1
;;
esac
done

# -------------------------------
# Semgrep
# -------------------------------

echo -e "${BLUE}[*] Code security (Semgrep)${RESET}"

if [ "$MODE" = "deep" ]; then
    echo -e "${YELLOW}[i] Running deep scan (Semgrep auto rules)${RESET}"
    if !uvx semgrep scan; then
        echo -e "${RED}[!] Semgrep (deep) found issues${RESET}"
    fi
else
    echo -e "${YELLOW}[i] Running light scan (p/security-audit)${RESET}"
    if ! uvx semgrep --config p/security-audit; then
        echo -e "${RED}[!] Semgrep (light) found issues${RESET}"
    fi
fi

echo

# -------------------------------
# pip-audit
# -------------------------------

echo -e "${BLUE}[*] Dependency audit (pip-audit)${RESET}"

REQS=$(mktemp)
poetry export -f requirements.txt --without-hashes > "$REQS"

if ! uvx pip-audit -r "$REQS"; then
    echo -e "${RED}[!] Vulnerable dependencies found${RESET}"
fi

rm -f "$REQS"

echo
echo -e "${GREEN}[✓] Audit completed (${MODE})${RESET}"
