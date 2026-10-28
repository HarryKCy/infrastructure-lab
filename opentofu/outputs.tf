output "lab" {
  description = "Owned domain UUIDs and expected allocations for discovery and verification."
  value = {
    prefix  = var.resource_prefix
    network = var.network_name
    pool    = var.storage_pool
    nodes = { for name, node in libvirt_domain.node : name => {
      uuid       = node.uuid
      vcpu       = var.vcpu
      memory_mib = var.memory_mib
      disk_gib   = var.disk_gib
      disk       = libvirt_volume.disk[name].name
      web        = name == var.vm_names[var.vm_count - 1]
    } }
  }
}
