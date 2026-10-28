#!/usr/bin/env bash
set -euo pipefail
LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/env.sh
source "$LAB_ROOT/scripts/env.sh"
exec python3 "$LAB_ROOT/scripts/lab.py" "discover" "$@"
