#!/usr/bin/env bash
set -euo pipefail
LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/env.sh
source "$LAB_ROOT/scripts/env.sh"
cd "$LAB_ROOT"
for tool in tofu ansible-playbook ansible-inventory yamllint pytest shellcheck actionlint cloud-init; do
  command -v "$tool" >/dev/null || { echo "ERROR: missing required validation tool: $tool" >&2; exit 1; }
done
tofu -chdir=opentofu fmt -check -recursive
tofu -chdir=opentofu init -backend=false -input=false -lockfile=readonly
python3 scripts/verify-provider.py
tofu -chdir=opentofu validate
python3 scripts/static-fixtures.py
tofu -chdir=opentofu test -var-file=../.local/static/fixtures.tfvars.json
/usr/bin/python3 scripts/validate-cloud-init.py
ansible-inventory -i ansible/inventories/example/hosts.yml --list >/dev/null
for playbook in ansible/playbooks/*.yml; do
  ansible-playbook -i ansible/inventories/example/hosts.yml "$playbook" --syntax-check
done
yamllint .
shellcheck scripts/*.sh
actionlint .github/workflows/validate.yml
pytest -q tests
python3 scripts/hygiene.py
