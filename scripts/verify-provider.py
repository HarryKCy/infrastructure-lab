#!/usr/bin/env python3
"""Check installed provider against upstream release; registry has no signing key."""
import hashlib
from pathlib import Path
import urllib.request
import zipfile

root = Path(__file__).resolve().parents[1]
cache = root / '.local/downloads'
cache.mkdir(parents=True, exist_ok=True)
name = 'terraform-provider-libvirt_0.9.9_linux_amd64.zip'
archive = cache / name
if not archive.exists():
    with urllib.request.urlopen('https://github.com/dmacvicar/terraform-provider-libvirt/releases/download/v0.9.9/' + name, timeout=60) as response:
        archive.write_bytes(response.read())
if hashlib.sha256(archive.read_bytes()).hexdigest() != '70a9d5af99a60179c7d38032662f443c3d2ad8bddab11d535c545c5c44273b2d':
    raise SystemExit('Upstream provider archive checksum mismatch')
binary = 'terraform-provider-libvirt_v0.9.9'
installed = root / 'opentofu/.terraform/providers/registry.opentofu.org/dmacvicar/libvirt/0.9.9/linux_amd64' / binary
with zipfile.ZipFile(archive) as bundle:
    if hashlib.sha256(bundle.read(binary)).digest() != hashlib.sha256(installed.read_bytes()).digest():
        raise SystemExit('Installed provider differs from verified upstream binary')
print('PASS: installed libvirt provider matches pinned upstream release asset')
