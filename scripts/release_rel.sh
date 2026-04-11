#!/usr/bin/env bash
set -euo pipefail

bash scripts/release_audit.sh

SKIP_RELEASE_AUDIT=1 ALLOW_MAIN_PUSH=1 git push
