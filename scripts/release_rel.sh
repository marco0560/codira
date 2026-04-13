#!/usr/bin/env bash
set -euo pipefail

echo "== Release pipeline =="

echo "[0] Checking virtual environment..."
if ! python -c "import pathlib, sys; sys.exit(0 if sys.prefix != sys.base_prefix and (pathlib.Path(sys.prefix) / 'pyvenv.cfg').exists() else 1)"; then
    echo "ERROR: the script must be run inside the project virtual environment"
    exit 1
fi

echo "[1] Sync with remote..."
git fetch
git pull --ff-only

echo "[2] Running release_audit.sh..."
bash scripts/release_audit.sh
SKIP_RELEASE_AUDIT=1 ALLOW_MAIN_PUSH=1 git push

echo "[3] Waiting for CI/tag propagation..."
sleep 30

echo "[4] Sync again..."
git fetch -q
git pull --ff-only -q

echo "[5] Cleaning build artifacts..."
rm -rf dist build
find . -maxdepth 1 -type d -name '*.egg-info' -exec rm -rf {} +

echo "[6] Checking build backend availability..."
python -c "import build" >/dev/null 2>&1 || {
    echo "ERROR: Python package 'build' is not installed in the active environment"
    exit 1
}

echo "[7] Building package..."
python -m build --wheel --no-isolation > /dev/null

echo "[8] Installing latest wheel..."
WHEEL="$(ls -t dist/*.whl | head -n1)"

if [ -z "$WHEEL" ]; then
    echo "ERROR: no wheel found in dist/"
    exit 1
fi

python -m pip install --force-reinstall --no-deps -q "$WHEEL"

echo "[9] Verifying version..."
codira -V

echo "== Release pipeline completed =="
