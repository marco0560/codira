#!/usr/bin/env bash
set -euo pipefail

echo "== Release pipeline =="

echo "[1] Sync with remote..."
git fetch
git pull --ff-only

echo "[2] Running release_rel.sh..."
bash scripts/release_ausit.sh
SKIP_RELEASE_AUDIT=1 ALLOW_MAIN_PUSH=1 git push

echo "[3] Waiting for CI/tag propagation..."
sleep 30

echo "[4] Sync again..."
git fetch
git pull --ff-only

echo "[5] Cleaning build artifacts..."
rm -rf dist build *.egg-info

echo "[6] Building package..."
poetry build > /dev/null

echo "[7] Installing latest wheel..."
WHEEL="$(ls -t dist/*.whl | head -n1)"

if [ -z "$WHEEL" ]; then
    echo "ERROR: no wheel found in dist/"
    exit 1
fi

poetry run pip install --force-reinstall "$WHEEL"

echo "[8] Verifying version..."
codira -V

echo "== Release pipeline completed =="
