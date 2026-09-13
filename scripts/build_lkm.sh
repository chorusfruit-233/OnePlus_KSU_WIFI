#!/usr/bin/env bash
# Compatibility wrapper; the Python implementation isolates the target ABI and build tree.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 "$ROOT/scripts/build_lkm.py" "$@"
