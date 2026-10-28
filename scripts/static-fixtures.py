#!/usr/bin/env python3
"""Synthetic public material only. These files must NEVER be used for deployment."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
local = root / '.local/static'
local.mkdir(parents=True, exist_ok=True)
(local / 'instance-data.json').write_text('{}')
# RFC 8032 test-vector public key, encoded as an OpenSSH Ed25519 public key.
import base64
import struct
public = bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
wire = struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32) + public
(local / 'synthetic.pub').write_text('ssh-ed25519 ' + base64.b64encode(wire).decode() + ' synthetic-test-only\n')
image = local / 'NOT-A-BOOTABLE-IMAGE'
image.write_bytes(b'synthetic validation fixture; never deploy\n')
variables = {'ssh_public_key_path': str(local / 'synthetic.pub'), 'image_path': str(image),
             'image_sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
(local / 'fixtures.tfvars.json').write_text(json.dumps(variables))
result = subprocess.run(['tofu', f'-chdir={root / "opentofu"}', 'console',
                         f'-var-file={local / "fixtures.tfvars.json"}'],
                        input='jsonencode(local.user_data)\n', text=True, capture_output=True, check=True)
for name, value in json.loads(json.loads(result.stdout)).items():
    (local / f'{name}.yaml').write_text(value)

result = subprocess.run(['tofu', f'-chdir={root / "opentofu"}', 'console',
                         f'-var-file={local / "fixtures.tfvars.json"}'],
                        input='local.network_config\n', text=True, capture_output=True, check=True)
# OpenTofu console emits multiline strings as heredocs.
lines = result.stdout.splitlines()
if not lines[0].startswith('<<') or lines[-1] != lines[0][2:]:
    raise SystemExit('Unexpected console heredoc output')
(local / 'network.yaml').write_text('\n'.join(lines[1:-1]) + '\n')
