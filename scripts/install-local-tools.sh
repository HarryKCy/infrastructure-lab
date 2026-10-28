#!/usr/bin/env bash
# Project-local tooling only. No privileged installation or shell profile changes.
set -euo pipefail
LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$LAB_ROOT"
mkdir -p .local/bin .local/downloads .local/gnupg
chmod 700 .local/gnupg
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock.txt
base=https://github.com/opentofu/opentofu/releases/download/v1.13.2
for artifact in tofu_1.13.2_linux_amd64.zip tofu_1.13.2_SHA256SUMS tofu_1.13.2_SHA256SUMS.gpgsig; do
  curl --proto '=https' --tlsv1.2 -fLsS "$base/$artifact" -o ".local/downloads/$artifact"
done
curl --proto '=https' --tlsv1.2 -fLsS https://get.opentofu.org/opentofu.asc -o .local/downloads/opentofu.asc
fingerprint=E3E6E43D84CB852EADB0051D0C0AF313E5FD9F80
gpg --homedir .local/gnupg --batch --with-colons --show-keys .local/downloads/opentofu.asc > .local/downloads/key-info
if ! awk -F: -v fp="$fingerprint" '$1 == "fpr" && $10 == fp {found=1} END {exit !found}' .local/downloads/key-info; then
  echo 'ERROR: unexpected OpenTofu signing fingerprint' >&2
  exit 1
fi
gpg --homedir .local/gnupg --batch --import .local/downloads/opentofu.asc
gpg --homedir .local/gnupg --batch --verify .local/downloads/tofu_1.13.2_SHA256SUMS.gpgsig .local/downloads/tofu_1.13.2_SHA256SUMS
python3 - <<'PY'
import hashlib
from pathlib import Path
import zipfile
root = Path('.local/downloads')
name = 'tofu_1.13.2_linux_amd64.zip'
expected = [line.split()[0] for line in (root / 'tofu_1.13.2_SHA256SUMS').read_text().splitlines() if line.split()[-1] == name]
with (root / name).open('rb') as stream:
    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
if expected != [actual]:
    raise SystemExit('OpenTofu archive checksum mismatch')
with zipfile.ZipFile(root / name) as archive:
    Path('.local/bin/tofu').write_bytes(archive.read('tofu'))
Path('.local/bin/tofu').chmod(0o755)
PY
.local/bin/tofu version
