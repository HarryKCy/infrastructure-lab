# Infrastructure Engineering Lab

A local QEMU/KVM lab for two Ubuntu 24.04 guests. OpenTofu manages project disks, cloud-init seeds and domains on `qemu:///system`; Ansible manages a Linux baseline and an Nginx `/health` endpoint on the second node. Existing libvirt NAT networks and directory storage pools remain outside OpenTofu management.

The default allocation is two vCPUs, 3072 MiB RAM and a sparse 30 GiB qcow2 root disk per guest. There are no cloud accounts, public port forwards, Kubernetes or monitoring components.

The existing lab has passed actual runtime acceptance. Both original VMs are running with verified UUIDs, allocations, sparse disks, seed attachments, VirtIO and NAT/DHCP. Authorized UNIX guest-agent channel repair and controlled ACPI recovery restored guest-agent communication. Ubuntu/cloud-init, trusted SSH, Ansible bootstrap/configuration/verification, Nginx HTTP health and actual idempotency all pass. The fresh unapplied OpenTofu plan proposes zero additions, two in-place domain updates and zero deletions; the engineering report explains the remaining source/read-only representation differences. Existing disks and saved state were preserved.

This repository contains reusable infrastructure automation. Deployment requires an existing KVM/libvirt environment, verified prerequisites, private SSH configuration, and review of the OpenTofu execution plan. The existing lab uses network `default` and pool `infra-lab`; reusable defaults must be overridden in private variables where appropriate.

Run `scripts/validate.sh` for static checks. On a fresh workstation, the project tooling installers are `scripts/install-local-tools.sh` and `scripts/install-actionlint.py`; host prerequisites are documented separately. Tooling, images, state, SSH keys, inventory, known_hosts and logs remain ignored. Never deploy the synthetic static-test inputs.

Local validation passes: 14 mocked OpenTofu tests, 135 Python/integration tests, cloud-init schemas, Ansible syntax, YAML lint, ShellCheck, actionlint and basic publication hygiene. GitHub-hosted CI must be verified separately. Runtime validation was performed on a personal Ubuntu/KVM laboratory.
