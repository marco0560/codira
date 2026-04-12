#!/bin/sh
set -eu
rm -rf dist build *.egg-info
poetry build
