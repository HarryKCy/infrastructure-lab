variable "vm_names" {
  type    = list(string)
  default = ["infra-node-01", "infra-node-02"]
  validation {
    condition = length(var.vm_names) == length(distinct(var.vm_names)) && alltrue([
      for n in var.vm_names : can(regex("^[a-z][a-z0-9-]{0,61}[a-z0-9]$", n))
    ])
    error_message = "VM names must be unique DNS hostnames, 2–63 characters."
  }
}
variable "vm_count" {
  type    = number
  default = 2
  validation {
    condition     = var.vm_count >= 1 && var.vm_count <= 2 && floor(var.vm_count) == var.vm_count
    error_message = "Initial lab supports one or two VMs only."
  }
}
variable "vcpu" {
  type    = number
  default = 2
  validation {
    condition     = var.vcpu >= 1 && var.vcpu <= 4 && floor(var.vcpu) == var.vcpu
    error_message = "vCPU must be an integer from 1 to 4."
  }
}
variable "memory_mib" {
  type    = number
  default = 3072
  validation {
    condition     = var.memory_mib >= 1024 && var.memory_mib <= 8192 && floor(var.memory_mib) == var.memory_mib
    error_message = "RAM must be an integer from 1024 to 8192 MiB."
  }
}
variable "disk_gib" {
  type    = number
  default = 30
  validation {
    condition     = var.disk_gib >= 10 && var.disk_gib <= 60 && floor(var.disk_gib) == var.disk_gib
    error_message = "Disk must be an integer from 10 to 60 GiB."
  }
}
variable "allow_budget_override" {
  type    = bool
  default = false
}
variable "resource_prefix" {
  type    = string
  default = "infra-lab"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,23}$", var.resource_prefix))
    error_message = "Prefix must be 2–24 lowercase letters, digits or hyphens, starting with a letter."
  }
}
variable "storage_pool" {
  type    = string
  default = "default"
  validation {
    condition     = can(regex("^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$", var.storage_pool))
    error_message = "Use an existing, named directory storage pool."
  }
}
variable "network_name" {
  type    = string
  default = "default"
  validation {
    condition     = can(regex("^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$", var.network_name))
    error_message = "Use an existing NAT network name, not an interface or URI."
  }
}
variable "ssh_public_key_path" {
  type = string
  validation {
    condition     = endswith(var.ssh_public_key_path, ".pub") && fileexists(pathexpand(var.ssh_public_key_path))
    error_message = "Supply an existing .pub file; never supply a private key."
  }
}
variable "image_path" {
  type    = string
  default = "../.local/images/ubuntu-24.04-server-cloudimg-amd64.img"
  validation {
    condition     = fileexists(pathexpand(var.image_path))
    error_message = "Run scripts/fetch-image.py to download and authenticate the image first."
  }
}
variable "image_sha256" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.image_sha256))
    error_message = "Provide the SHA256 from the authenticated Canonical manifest."
  }
}
