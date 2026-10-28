#!/usr/bin/env python3
"""Authenticate Canonical's manifest before downloading/reusing one pinned image."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://cloud-images.ubuntu.com/releases/noble/release-20261017/'
NAME = 'ubuntu-24.04-server-cloudimg-amd64.img'
KEYRING = Path('/usr/share/keyrings/ubuntu-cloudimage-keyring.gpg')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, path):
    temporary = path.with_suffix(path.suffix + '.part')
    try:
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as stream:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    if not KEYRING.is_file():
        raise SystemExit('Missing Ubuntu cloud-image trust keyring. Owner: install ubuntu-cloudimage-keyring from Ubuntu apt.')
    cache = ROOT / '.local/images'
    cache.mkdir(parents=True, exist_ok=True)
    for name in ('SHA256SUMS', 'SHA256SUMS.gpg'):
        download(BASE + name, cache / name)
    subprocess.run(['gpgv', '--keyring', str(KEYRING), str(cache / 'SHA256SUMS.gpg'),
                    str(cache / 'SHA256SUMS')], check=True)
    matches = [line.split()[0] for line in (cache / 'SHA256SUMS').read_text().splitlines()
               if line.split()[-1].lstrip('*') == NAME]
    if len(matches) != 1:
        raise SystemExit('Manifest must contain exactly one matching image.')
    image = cache / NAME
    expected = matches[0]
    if not image.exists():
        print('Downloading pinned amd64 image...', flush=True)
        download(BASE + NAME, image)
    if digest(image) != expected:
        raise SystemExit('Image checksum FAILED. Quarantine/remove the cached image manually and retry.')
    info = json.loads(subprocess.check_output(['qemu-img', 'info', '--output=json', str(image)], text=True))
    if info['format'] != 'qcow2' or info.get('backing-filename') or info['virtual-size'] > 30 * 2**30:
        raise SystemExit('Unexpected image format, backing file, or capacity.')
    (cache / 'verified.json').write_text(json.dumps({'source': BASE + NAME, 'sha256': expected,
                                                  'qemu_img': info}, indent=2) + '\n')
    print(f'Authenticated amd64 qcow2 image: {image}\nimage_sha256 = "{expected}"')


if __name__ == '__main__':
    main()
