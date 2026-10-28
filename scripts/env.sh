#!/usr/bin/env bash
# Source from repository root, or source using its absolute path.
# Generated state, inventories, recaps and logs must stay private.
umask 077
LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$LAB_ROOT/.local/bin:$LAB_ROOT/.venv/bin:$PATH"
export ANSIBLE_CONFIG="$LAB_ROOT/ansible/ansible.cfg"
export ANSIBLE_LOCAL_TEMP="$LAB_ROOT/.local/ansible/tmp"
export ANSIBLE_ROLES_PATH="$LAB_ROOT/ansible/roles"
