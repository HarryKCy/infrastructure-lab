#!/usr/bin/env python3
"""Check the publishable file set, including untracked implementation files."""
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root).decode().split('\0')
errors = []
for name in filter(None, files):
    path = root / name
    if any(part in {'.local', '.venv', '.terraform'} for part in path.parts) or re.search(r'\.tfstate(?:\.|$)', name):
        errors.append(f'{name}: private runtime artifact')
    if path.suffix in {'.tfstate', '.tfplan', '.img', '.qcow2', '.iso', '.pem', '.key', '.log'} or name.endswith('.tfvars'):
        errors.append(f'{name}: forbidden artifact')
    try:
        data = path.read_text()
    except (UnicodeDecodeError, OSError):
        errors.append(f'{name}: unreadable or binary artifact requires review')
        continue
    if re.search(r'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----', data):
        errors.append(f'{name}: private key')
    if re.search(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16})', data):
        errors.append(f'{name}: credential pattern')
    if re.search(r'/home/[a-zA-Z][a-zA-Z0-9_-]+/', data):
        errors.append(f'{name}: personal absolute path')
if errors:
    raise SystemExit('\n'.join(errors))
print('PASS: publishable-file hygiene and basic credential patterns (not a comprehensive secret audit)')
