#!/usr/bin/env bash
# Guided setup by default; explicit subcommands are suitable for maintenance.
set -euo pipefail
if ! command -v python3 >/dev/null 2>&1; then
  printf 'Python 3 is required. Install it with your OS package manager first.\n' >&2
  exit 1
fi
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/toolkit.py" "$@"
