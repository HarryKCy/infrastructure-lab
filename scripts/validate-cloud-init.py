#!/usr/bin/python3
"""Use Ubuntu's installed schema library without probing the host datasource."""
from pathlib import Path
import yaml
from cloudinit.config.schema import validate_cloudconfig_schema, SchemaType

root = Path(__file__).resolve().parents[1] / '.local/static'
for path in root.glob('infra-node-*.yaml'):
    if not validate_cloudconfig_schema(yaml.safe_load(path.read_text()), strict=True):
        raise SystemExit(f'Schema validation unavailable: {path}')
    print(f'PASS: cloud-init schema {path.name}')
if not validate_cloudconfig_schema(yaml.safe_load((root / 'network.yaml').read_text()),
                                   schema_type=SchemaType.NETWORK_CONFIG_V2, strict=True):
    raise SystemExit('Network schema validation unavailable')
print('PASS: cloud-init network v2 schema')
