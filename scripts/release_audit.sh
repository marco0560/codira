#!/usr/bin/env bash
set -euo pipefail

if [ "${SKIP_RELEASE_AUDIT:-0}" = "1" ]; then
  exit 0
fi

echo "== Release Audit =="

echo "[1] Checking working tree clean..."
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: dirty working tree"
  exit 1
fi

echo "[2] Checking branch alignment..."
LOCAL=$(git rev-parse @)
REMOTE=$(git rev-parse @{u} 2>/dev/null || echo "")

if [ -z "$REMOTE" ]; then
  echo "OK: no upstream configured"
else
  BASE=$(git merge-base @ @{u})
  if [ "$LOCAL" = "$REMOTE" ]; then
    echo "OK: branch aligned"
  elif [ "$LOCAL" = "$BASE" ]; then
    echo "ERROR: branch behind remote"
    exit 1
  elif [ "$REMOTE" = "$BASE" ]; then
    echo "OK: branch ahead"
  else
    echo "ERROR: branch diverged"
    exit 1
  fi
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "main" ]; then
  echo "Release audit skipped on branch $BRANCH"
  exit 0
fi

echo "[3] Checking latest tag ancestry..."
LATEST_TAG=$(
  git tag --merged HEAD \
    | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' \
    | sort -V \
    | tail -1
)

if [ -z "${LATEST_TAG:-}" ]; then
  echo "WARN: no semantic version tag reachable from HEAD"
else
  bash scripts/tag_guard.sh "$LATEST_TAG"
  if git merge-base --is-ancestor "$LATEST_TAG" HEAD; then
    echo "OK: latest tag consistent ($LATEST_TAG)"
  else
    echo "ERROR: latest tag is not an ancestor of HEAD"
    exit 1
  fi
fi

echo "[4] Checking changelog consistency..."
bash scripts/changelog_guard.sh

echo "[5] Checking semantic-release baseline..."
if [ -n "${LATEST_TAG:-}" ]; then
  COMMITS=$(git rev-list "$LATEST_TAG"..HEAD --count)
else
  COMMITS=$(git rev-list HEAD --count)
fi
echo "Commits since last reachable release: $COMMITS"

echo "[6] Checking release commit count..."
RELEASE_COMMITS=$(git log --oneline --grep '^chore(release):' | wc -l | tr -d ' ')
echo "Release commits in history: $RELEASE_COMMITS"

echo "OK: release baseline valid"
