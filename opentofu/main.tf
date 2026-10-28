# Existing pools and networks are deliberately not managed by this project.
resource "libvirt_volume" "base" {
  name       = "${var.resource_prefix}-ubuntu-base.qcow2"
  pool       = var.storage_pool
  target     = { format = { type = "qcow2" } }
  create     = { content = { url = abspath(pathexpand(var.image_path)) } }
  depends_on = [terraform_data.guardrails]
}
resource "libvirt_volume" "disk" {
  for_each   = local.nodes
  name       = "${var.resource_prefix}-${each.key}.qcow2"
  pool       = var.storage_pool
  capacity   = var.disk_gib * 1024 * 1024 * 1024
  allocation = 0
  target     = { format = { type = "qcow2" } }
  backing_store = {
    path   = libvirt_volume.base.path
    format = { type = "qcow2" }
  }
  lifecycle {
    replace_triggered_by = [libvirt_volume.base]
  }
}
resource "libvirt_cloudinit_disk" "seed" {
  for_each  = local.nodes
  name      = "${var.resource_prefix}-${each.key}-seed"
  user_data = local.user_data[each.key]
  meta_data = templatefile("${path.module}/cloud-init/meta-data.yaml.tftpl", {
    hostname    = each.key
    instance_id = "${var.resource_prefix}-${each.key}-${substr(sha256(local.user_data[each.key]), 0, 12)}"
  })
  network_config = local.network_config
  depends_on     = [terraform_data.guardrails]
}
resource "libvirt_volume" "seed" {
  for_each = local.nodes
  name     = "${var.resource_prefix}-${each.key}-seed.iso"
  pool     = var.storage_pool
  target   = { format = { type = "iso" } }
  create   = { content = { url = libvirt_cloudinit_disk.seed[each.key].path } }
}
resource "libvirt_domain" "node" {
  for_each    = local.nodes
  name        = each.key
  type        = "kvm"
  memory      = var.memory_mib
  memory_unit = "MiB"
  vcpu        = var.vcpu
  running     = true
  autostart   = false
  os = {
    type = "hvm", type_arch = "x86_64", type_machine = "q35", boot_devices = [{ dev = "hd" }]
  }
  devices = {
    disks = [
      {
        device = "disk"
        driver = { name = "qemu", type = "qcow2" }
        source = { file = { file = libvirt_volume.disk[each.key].path } }
        target = { dev = "vda", bus = "virtio" }
      },
      {
        device    = "cdrom"
        driver    = { name = "qemu", type = "raw" }
        source    = { file = { file = libvirt_volume.seed[each.key].path } }
        target    = { dev = "sda", bus = "sata" }
        read_only = true
      }
    ]
    interfaces = [{
      model       = { type = "virtio" }
      source      = { network = { network = var.network_name } }
      wait_for_ip = { source = "lease", timeout = 300, network = "0.0.0.0/0" }
    }]
    channels = [{
      source = { unix = { mode = "bind" } }
      target = { virt_io = { name = "org.qemu.guest_agent.0" } }
    }]
    consoles = [{ type = "pty", target = { type = "serial", port = 0 } }]
  }
  lifecycle {
    replace_triggered_by = [libvirt_volume.disk[each.key], libvirt_volume.seed[each.key]]
  }
}
