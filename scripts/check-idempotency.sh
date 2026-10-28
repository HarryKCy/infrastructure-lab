#!/usr/bin/env bash
set -euo pipefail
LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/env.sh
source "$LAB_ROOT/scripts/env.sh"
cd "$LAB_ROOT"
# A real, complete configuration run is required; selection/check-mode flags can
# otherwise produce an empty or partial recap that looks idempotent.
arguments=("$@")
while (($#)); do
  case "$1" in
    --private-key|--key-file)
      (($# >= 2)) || { echo "ERROR: $1 requires a path" >&2; exit 2; }
      shift 2 ;;
    -v|-vv|-vvv|-vvvv) shift ;;
    *) echo "ERROR: unsupported idempotency argument: $1 (use --private-key PATH and optional verbosity)" >&2; exit 2 ;;
  esac
done
set -- "${arguments[@]}"
export ANSIBLE_CALLBACK_PLUGINS="$LAB_ROOT/ansible/callback_plugins"
export ANSIBLE_CALLBACKS_ENABLED=lab_stats
export LAB_STATS_FILE="$LAB_ROOT/.local/idempotency.json"
ansible-playbook -i .local/inventory.json ansible/playbooks/configure.yml "$@"
rm -f "$LAB_STATS_FILE"
ansible-playbook -i .local/inventory.json ansible/playbooks/configure.yml "$@"
python3 scripts/lab.py check-idempotency
