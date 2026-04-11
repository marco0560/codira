#!/usr/bin/env bash
set -euo pipefail

if [ ! -f CHANGELOG.md ]; then
  echo "ERROR: CHANGELOG.md not found"
  exit 1
fi

TOP_VERSION=$(
  sed -n 's/^#\{1,2\} \[\([0-9][0-9.]*\)\].*/\1/p' CHANGELOG.md | head -1
)

if [ -z "${TOP_VERSION:-}" ]; then
  echo "ERROR: CHANGELOG.md does not start with a released version heading"
  exit 1
fi

DUPLICATES=$(
  sed -n 's/^#\{1,2\} \[\([0-9][0-9.]*\)\].*/\1/p' CHANGELOG.md \
    | sort \
    | uniq -d
)

if [ -n "${DUPLICATES:-}" ]; then
  echo "ERROR: duplicate release entries found in CHANGELOG.md"
  printf '%s\n' "$DUPLICATES"
  exit 1
fi

LATEST_TAG=$(
  git tag --merged HEAD \
    | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' \
    | sort -V \
    | tail -1
)

if [ -n "${LATEST_TAG:-}" ]; then
  LATEST_VERSION=${LATEST_TAG#v}
  if [ "$TOP_VERSION" != "$LATEST_VERSION" ]; then
    echo "ERROR: top CHANGELOG version ($TOP_VERSION) does not match latest tag ($LATEST_TAG)"
    exit 1
  fi
fi
