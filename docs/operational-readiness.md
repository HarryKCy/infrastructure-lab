# Operational readiness — KVM/Ansible infrastructure lab

## Scope
This document builds on a personal two-VM KVM/libvirt lab. It does **not** claim automated disaster recovery or real production operation.

## Acceptance gates
1. `tofu fmt -check`, `tofu validate`, Python tests and Ansible lint/static checks succeed.
2. `tofu plan` produces no unexplained changes **after a previously reviewed apply**.
3. Existing VMs, volumes, network names, and private state are inspected before any change.
4. The nginx `/health` check passes from the authorized lab host.
5. Ansible can be run twice without unexpected changes.
6. A controlled outage is detected and recovery is verified.

## Drift investigation (read-only first)
```bash
source scripts/env.sh
tofu -chdir=opentofu state list
tofu -chdir=opentofu plan -refresh-only
virsh -c qemu:///system list --all
virsh -c qemu:///system vol-list default
```

Compare the plan and libvirt resources; diagnose provider-computed attributes, guest changes, or configuration differences. **Do not** run `apply -refresh-only`, remove state entries, import resources, or destroy VMs without understanding the implications and preserving state backups.

## Incident drill
1. Establish normal probe measurements for the lab-only `/health` endpoint.
2. Stop nginx on the designated **disposable** test guest.
3. Verify the probe detects failure; record detection interval.
4. Restart nginx through approved Ansible/systemd procedure.
5. Verify consecutive successful probes; record recovery interval.
6. Write an incident timeline, hypothesis, impact and prevention actions.

Tools: `python3 tools/availability_probe.py --url http://<LAB_IP>/health --count 10`.
Do not target public systems or modify any live infrastructure with this drill.
