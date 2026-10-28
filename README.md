# Infrastructure Engineering Lab

[![Static validation](https://github.com/HarryKCy/infrastructure-lab/actions/workflows/validate.yml/badge.svg)](https://github.com/HarryKCy/infrastructure-lab/actions/workflows/validate.yml)

**Reproducible Linux VM provisioning and configuration on a personal KVM/libvirt host.**

This lab uses **OpenTofu**, **QEMU/KVM + libvirt**, **Ubuntu Server 24.04 cloud images**, **cloud-init**, and **Ansible** to create two virtual machines, configure them over SSH, and verify a small Nginx application. GitHub Actions checks the infrastructure code without requiring access to the author's hypervisor.

It is a hands-on infrastructure engineering project, **not** a production platform, hosted service, or generic VM management product.

## What it demonstrates

- **Infrastructure as Code:** a declared, reviewable VM topology managed using OpenTofu and the libvirt provider.
- **Repeatable guest initialization:** cloud-init creates the lab account, configures key-based SSH and initializes the guest agent.
- **Configuration management:** Ansible applies a Linux baseline and configures an Nginx health endpoint on the second VM.
- **Verification:** explicit checks for VM identity, storage, network, guest readiness, SSH trust, service health, and playbook idempotency.
- **Operational safety:** separate local state and credentials; preflight collision checks; no automatic deletion of existing libvirt networks or storage pools.
- **Continuous integration:** static validation and synthetic tests on GitHub Actions, separate from real VM deployment.

## Architecture

```text
              Personal Ubuntu 24.04 host
  +--------------------------------------------------+
  |  OpenTofu -> libvirt (qemu:///system)              |
  |           |                                      |
  |           +-- existing NAT network: default      |
  |           +-- existing directory storage pool   |
  |                        |                         |
  |       +----------------+----------------+        |
  |       |                                 |        |
  |  infra-node-01                    infra-node-02   |
  |  Ubuntu Server 24.04              Ubuntu Server 24.04
  |  2 vCPU / 3 GiB RAM               2 vCPU / 3 GiB RAM
  |  30 GiB qcow2                     30 GiB qcow2   |
  |  cloud-init + SSH                 cloud-init + SSH
  |       |                                 |        |
  |       +----------- Ansible ------------+        |
  |                                         |        |
  |                                    Nginx /health |
  +--------------------------------------------------+

 GitHub Actions: validates source/configuration only;
                 does not connect to the local hypervisor.
```

Both guests use DHCP on libvirt's local NAT network; no physical-LAN bridge or public port forwarding is configured by this project. The project reuses existing libvirt network and pool resources rather than managing their creation or deletion.

## Default VM layout

| Guest | vCPU | RAM | Virtual root disk | Purpose |
| --- | ---: | ---: | ---: | --- |
| `infra-node-01` | 2 | 3 GiB | 30 GiB qcow2 | Linux baseline and configuration validation |
| `infra-node-02` | 2 | 3 GiB | 30 GiB qcow2 | Linux baseline plus Nginx `/health` |

The guests use independent qcow2 overlays backed by a verified Ubuntu base image. Their **virtual disk capacity** is 30 GiB each; actual host disk usage grows with data written. Resource figures describe allocations, not measured CPU or memory consumption.

## Requirements

- Linux x86-64 host with hardware virtualization and usable `/dev/kvm`.
- QEMU/KVM and a working **system** libvirt connection (`qemu:///system`).
- An active libvirt NAT network and an active **directory-backed** storage pool with adequate space. The example defaults use `default`; select existing resources appropriate to your host.
- OpenTofu and compatible `dmacvicar/libvirt` provider (validated with **OpenTofu 1.13.2** and **provider 0.9.9**).
- Python 3.12 and project dependencies/tools; Ansible Core (locally tested with **2.19.3**); standard utilities used by the scripts.
- An SSH client and a dedicated lab SSH key pair.
- A genuine Canonical Ubuntu Server 24.04 amd64 cloud image, with its **authenticated** digest recorded in private variables.

The provided bootstrap scripts set up project-local tooling, but **review installation scripts before running them**. Host KVM/libvirt setup and access control remain operator responsibilities; this repository does not grant itself host privileges.

> **Libvirt access:** `id -nG` must include the `libvirt` group in the *current shell*, and `virsh -c qemu:///system list --all` must succeed. Group changes often require a new login session. Running OpenTofu as root is not the recommended workaround.

## Quick start — on a new, disposable lab host

**Review the plan before any apply.** Do not use these instructions on hosts containing unmanaged or valuable VMs without first assessing resource naming and collision protections.

### 1. Clone and inspect

```bash
git clone https://github.com/HarryKCy/infrastructure-lab.git
cd infrastructure-lab

# Read these before running anything that downloads or installs tools.
sed -n '1,200p' scripts/install-local-tools.sh
sed -n '1,200p' scripts/fetch-image.py
```

Make sure the host has KVM/libvirt configured and that the selected NAT network and storage pool already exist:

```bash
id -nG
virsh -c qemu:///system list --all
virsh -c qemu:///system net-list --all
virsh -c qemu:///system pool-list --all
```

### 2. Prepare local tooling and a private SSH key

```bash
# Review first; installs the project's development tooling locally.
scripts/install-local-tools.sh
source scripts/env.sh

mkdir -p .local/ssh
chmod 700 .local/ssh
# Only on a new lab; do not overwrite an existing key.
ssh-keygen -t ed25519 -f .local/ssh/lab -C infrastructure-lab -N ''
chmod 600 .local/ssh/lab
chmod 644 .local/ssh/lab.pub
```

This dedicated key has no passphrase to support unattended operation in a **disposable personal lab**. Protect it and use a separate credential policy in other environments. Never commit private keys.

### 3. Fetch and authenticate the cloud image

```bash
scripts/fetch-image.py
```

Follow the script's signature and checksum validation results. Put the **authenticated SHA-256** it reports into your private configuration; do not trust an arbitrary downloaded image or substitute an unchecked digest.

### 4. Create private variables

```bash
cp opentofu/terraform.tfvars.example opentofu/terraform.tfvars
```

Edit `opentofu/terraform.tfvars` to set your key path, authenticated image checksum, and the existing storage pool and NAT network. The example has placeholders and must be reviewed before planning:

```hcl
ssh_public_key_path = "../.local/ssh/lab.pub"
image_sha256        = "<authenticated SHA-256 from fetch-image.py>"
storage_pool        = "<existing directory pool>"
network_name        = "<existing NAT network>"
```

`terraform.tfvars` and `.local/` are ignored by Git. **Do not commit OpenTofu state or machine-specific inventory.**

### 5. Validate, review, and provision

```bash
source scripts/env.sh
scripts/validate.sh
scripts/preflight.sh

tofu -chdir=opentofu init -input=false -lockfile=readonly
tofu -chdir=opentofu validate
tofu -chdir=opentofu plan -out=../.local/create.tfplan
tofu -chdir=opentofu show ../.local/create.tfplan
```

Inspect the *complete* resource list, names, and all proposed create/change/destroy actions. Only when appropriate for your disposable lab, apply the **reviewed saved plan**:

```bash
tofu -chdir=opentofu apply ../.local/create.tfplan
```

The preflight script is designed for the **initial** deployment; it may reject project-owned resources that already exist. Do not bypass that collision protection or repeatedly apply after a partial failure. Inspect OpenTofu state and actual libvirt resources first.

### 6. Discover and verify the existing guests

```bash
scripts/discover-vms.sh
scripts/verify-runtime.sh
python3 scripts/lab.py trust-hostkeys
```

These steps validate project identity and guest readiness before preparing the private Ansible inventory and trusted SSH host keys. Address discovered errors rather than disabling SSH verification.

### 7. Configure and verify with Ansible

```bash
ansible -i .local/inventory.json lab -m ping --private-key .local/ssh/lab

ansible-playbook -i .local/inventory.json ansible/playbooks/bootstrap.yml \
  --private-key .local/ssh/lab
ansible-playbook -i .local/inventory.json ansible/playbooks/configure.yml \
  --private-key .local/ssh/lab
ansible-playbook -i .local/inventory.json ansible/playbooks/verify.yml \
  --private-key .local/ssh/lab

scripts/check-idempotency.sh --private-key .local/ssh/lab
```

The verification playbook checks the intended services and health endpoint. The idempotency check requires the repeat run to complete without unnecessary Ansible changes, failures, or unreachable hosts.

### 8. Inspect state and plan for drift

```bash
scripts/lab-status.sh
tofu -chdir=opentofu state list
tofu -chdir=opentofu plan -input=false
```

**Do not auto-apply drift updates.** A no-change plan is the desired steady state, but some provider representation differences may require separate review.

## Validation and operational evidence

This project was exercised on a **personal Ubuntu 24.04.5** KVM host. During the initial operator-led deployment, two real VMs were created, rebooted under controlled conditions, and validated through cloud-init, QEMU guest-agent, trusted SSH, Ansible configuration, and Nginx service/HTTP checks. The second Ansible run reported **zero changes, failures, and unreachable hosts**.

| Check | Recorded result | Boundary |
| --- | --- | --- |
| OpenTofu synthetic tests | **14 passed** | Does not create VMs |
| Python/integration tests | **135 passed** | Predominantly isolated/synthetic tests |
| Cloud-init, Ansible syntax, YAML, ShellCheck, actionlint | Passed locally | Static checks |
| Two-VM provisioning and guest readiness | Passed on the personal lab | Actual local KVM runtime |
| SSH host-key verification and Ansible application | Passed on the personal lab | Actual guest runtime |
| Nginx `/health` and Ansible idempotency | Passed on the personal lab | Actual guest runtime |
| GitHub Actions | Initial `validate` workflow **passed** | Static CI only, not remote VM deployment |
| Final OpenTofu drift plan | **0 add, 2 in-place changes, 0 destroy** | **Not applied**; requires owner review |

The in-place changes concern the guest-agent channel source and CD-ROM read-only representation (and associated UUID output values). These differences remain an **open reconciliation item**. A successful application deployment must not be misrepresented as a zero-drift plan.

## Issues encountered and engineering decisions

The actual deployment exposed issues that static tests alone could not prove away:

- **Libvirt access:** a user with newly configured `libvirt` group membership could still lack effective permission in an existing shell.
- **CLI compatibility:** `virsh vol-list` does not accept the `--name` option; inventory collision checks had to parse its supported output without relaxing safety protections.
- **Provider volume formats:** libvirt reported cloud-init seed volumes as `iso`, while the original declaration expected `raw`. The mismatch caused a failed partial apply; state and volumes were inspected before a narrowly scoped recovery.
- **VM identity:** a libvirt domain's numeric runtime ID is not its stable UUID. Discovery now checks state-owned UUIDs.
- **QEMU guest agent:** the initial channel transport needed correction. Guest verification and trusted key collection were gated on operational guest-agent communication.

These are useful lessons from real integration—not evidence of production certification.

## Security and boundaries

- Initial automation is intended for **two disposable personal VMs**. Guest playbooks may use privilege escalation *inside the guests*, not on arbitrary hosts.
- OpenTofu manages project-owned domains, volumes, and cloud-init artifacts; it does **not** own or destroy the existing libvirt NAT network or storage pool.
- SSH uses dedicated lab keys and host-key verification. Avoid insecure SSH bypasses and committing secrets.
- Lab-specific state, keys, `terraform.tfvars`, generated inventories, images, logs, and tooling caches are excluded from Git; verify your staged files independently before publishing.
- CI does not have access to a contributor's KVM hypervisor. Passing GitHub Actions confirms static validation, **not** successful guest creation on every host.
- The lab cloud-init config permits passwordless sudo for a dedicated guest account, appropriate only to the disposable learning environment; do not reuse that policy blindly in production.
- No publicly exposed application ports, cloud accounts, or Kubernetes clusters are included in this first milestone.

## Cleanup and recovery

OpenTofu state is authoritative for resources managed by this project. Never manually remove unrelated libvirt volumes, networks, or pools just to make a plan clean.

A teardown must be **explicitly reviewed** and is destructive to the disposable guest disks and data:

```bash
tofu -chdir=opentofu state list
tofu -chdir=opentofu plan -destroy -out=../.local/destroy.tfplan
tofu -chdir=opentofu show ../.local/destroy.tfplan
# Review every planned deletion before deciding whether to execute:
# tofu -chdir=opentofu apply ../.local/destroy.tfplan
```

Do not follow this cleanup procedure on a host unless you have verified that the project owns every resource in the destroy plan. The existing libvirt network and pool are intentionally outside project state.

## Repository layout

```text
opentofu/     OpenTofu resources, guest variables, cloud-init templates and tests
ansible/      Common and webserver roles, playbooks and inventory example
scripts/      Preflight, image verification, discovery, runtime checks and helpers
tests/        Synthetic/integration regression tests
.github/      Static-validation workflow
```

## Scope and future extensions

This first milestone focuses on **repeatable provisioning and configuration**, not Kubernetes or cloud deployment. Reasonable later exercises include backup/restore validation, infrastructure failure recovery in disposable guests, and Kubernetes/GitOps—only after the underlying lifecycle remains reproducible.

## Maintainer

Harry Karasavvas · [GitHub profile](https://github.com/HarryKCy)

## License

No license has been assigned. Source visibility alone does not grant open-source reuse rights.
