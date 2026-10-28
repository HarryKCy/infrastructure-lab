mock_provider "libvirt" {}
run "default_lab" {
  command = plan
  assert {
    condition     = length(libvirt_domain.node) == 2 && libvirt_domain.node["infra-node-01"].vcpu == 2
    error_message = "Default must provision two small domains."
  }
  assert {
    condition     = libvirt_volume.disk["infra-node-02"].capacity == 32212254720 && libvirt_volume.disk["infra-node-02"].allocation == 0
    error_message = "Root disks must request sparse 30 GiB capacity."
  }
  assert {
    condition     = yamldecode(libvirt_cloudinit_disk.seed["infra-node-01"].user_data).ssh_pwauth == false
    error_message = "Password authentication must be disabled."
  }
  assert {
    condition = (
      libvirt_volume.seed["infra-node-01"].target.format.type == "iso" &&
      libvirt_domain.node["infra-node-01"].devices.disks[1].driver.type == "raw" &&
      libvirt_domain.node["infra-node-01"].devices.disks[1].device == "cdrom" &&
      libvirt_domain.node["infra-node-01"].devices.disks[1].read_only
    )
    error_message = "Seed volumes must retain ISO format with a read-only raw CD-ROM attachment."
  }
  assert {
    condition = alltrue([for node in libvirt_domain.node : (
      node.devices.channels[0].source.unix.mode == "bind" &&
      node.devices.channels[0].target.virt_io.name == "org.qemu.guest_agent.0"
    )])
    error_message = "Guest-agent channels must use the provider-supported UNIX socket source and VirtIO agent target."
  }
}
run "invalid_count" {
  command = plan
  variables { vm_count = 3 }
  expect_failures = [var.vm_count]
}
run "invalid_cpu" {
  command = plan
  variables { vcpu = 0 }
  expect_failures = [var.vcpu]
}
run "excess_memory" {
  command = plan
  variables { memory_mib = 4096 }
  expect_failures = [terraform_data.guardrails]
}
run "explicit_budget_override" {
  command = plan
  variables {
    memory_mib            = 4096
    allow_budget_override = true
  }
}
run "duplicate_names" {
  command = plan
  variables { vm_names = ["infra-node-01", "infra-node-01"] }
  expect_failures = [var.vm_names]
}
run "invalid_network" {
  command = plan
  variables { network_name = "../../invalid" }
  expect_failures = [var.network_name]
}
run "invalid_pool" {
  command = plan
  variables { storage_pool = "/dev/sda" }
  expect_failures = [var.storage_pool]
}
run "wrong_checksum" {
  command = plan
  variables { image_sha256 = "0000000000000000000000000000000000000000000000000000000000000000" }
  expect_failures = [terraform_data.guardrails]
}
run "mismatched_count" {
  command = plan
  variables { vm_count = 1 }
  expect_failures = [terraform_data.guardrails]
}

run "missing_public_key" {
  command = plan
  variables { ssh_public_key_path = "../.local/static/missing.pub" }
  expect_failures = [var.ssh_public_key_path]
}
run "invalid_disk" {
  command = plan
  variables { disk_gib = 0 }
  expect_failures = [var.disk_gib]
}
run "excess_cpu" {
  command = plan
  variables { vcpu = 3 }
  expect_failures = [terraform_data.guardrails]
}
run "missing_image" {
  command = plan
  variables { image_path = "../.local/static/missing.img" }
  expect_failures = [var.image_path]
}
