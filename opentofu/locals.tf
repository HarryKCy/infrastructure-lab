locals {
  network_config = yamlencode({
    version   = 2
    ethernets = { primary = { match = { name = "en*" }, dhcp4 = true, dhcp6 = false } }
  })
  nodes          = toset(slice(var.vm_names, 0, min(var.vm_count, length(var.vm_names))))
  ssh_public_key = trimspace(file(pathexpand(var.ssh_public_key_path)))
  user_data = { for name in local.nodes : name => templatefile("${path.module}/cloud-init/user-data.yaml.tftpl", {
    hostname   = name
    public_key = local.ssh_public_key
  }) }
}
resource "terraform_data" "guardrails" {
  input = var.resource_prefix
  lifecycle {
    precondition {
      condition     = length(var.vm_names) == var.vm_count
      error_message = "vm_names length must equal vm_count."
    }
    precondition {
      condition = var.allow_budget_override || (
        var.vm_count * var.vcpu <= 4 && var.vm_count * var.memory_mib <= 6144 && var.vm_count * var.disk_gib <= 60
      )
      error_message = "Budget exceeds 4 vCPU / 6144 MiB / 60 GiB. An explicit allow_budget_override is required."
    }
    precondition {
      condition     = can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) [A-Za-z0-9+/]+={0,3}( [^\\n]*)?$", local.ssh_public_key))
      error_message = "Supply one supported OpenSSH public key."
    }
    precondition {
      condition     = filesha256(pathexpand(var.image_path)) == var.image_sha256
      error_message = "Image does not match its authenticated SHA256."
    }
  }
}
