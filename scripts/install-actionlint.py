#!/usr/bin/env python3
"""Install release archive pinned to GitHub's authenticated asset SHA256."""
import hashlib
from pathlib import Path
import tarfile
import urllib.request

root = Path(__file__).resolve().parents[1]
cache = root / '.local/downloads'
cache.mkdir(parents=True, exist_ok=True)
name = 'actionlint_1.7.12_linux_amd64.tar.gz'
archive = cache / name
if not archive.exists():
    with urllib.request.urlopen('https://github.com/rhysd/actionlint/releases/download/v1.7.12/' + name, timeout=60) as response:
        archive.write_bytes(response.read())
if hashlib.sha256(archive.read_bytes()).hexdigest() != '8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8':
    raise SystemExit('actionlint archive checksum mismatch')
with tarfile.open(archive) as bundle:
    data = bundle.extractfile('actionlint').read()
target = root / '.local/bin/actionlint'
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(data)
target.chmod(0o755)
