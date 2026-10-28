#!/usr/bin/env python3
"""Small read-only libvirt helpers. All discovery is restricted to state-owned UUIDs."""
import argparse
import base64
import re
import time
import ipaddress
import json
import os
from pathlib import Path
import platform
import shutil
import shlex
import subprocess
import sys
import struct
import tempfile
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
URI = 'qemu:///system'


def run(args, stdin=None):
    result = subprocess.run(args, input=stdin, text=True, capture_output=True,
                            timeout=60, env={**os.environ, 'LC_ALL': 'C'})
    if result.returncode:
        raise ValueError(f"{' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def virsh(*args):
    return run(['virsh', '-c', URI, *args])


def config():
    keys = ['vm_names', 'vm_count', 'vcpu', 'memory_mib', 'disk_gib', 'resource_prefix',
            'storage_pool', 'network_name', 'ssh_public_key_path', 'image_path', 'image_sha256']
    expression = 'jsonencode({' + ','.join(f'{k}=var.{k}' for k in keys) + '})'
    result = run(['tofu', f'-chdir={ROOT / "opentofu"}', 'console'], expression + '\n')
    return json.loads(json.loads(result))


def stable_uuid(value):
    """Accept only canonical, nonzero UUIDs; runtime domain IDs are never identities."""
    if not isinstance(value, str):
        raise ValueError('Missing or malformed domain UUID in saved state')
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError('Missing or malformed domain UUID in saved state') from error
    if not parsed.int or str(parsed) != value.lower():
        raise ValueError('Missing or malformed domain UUID in saved state')
    return str(parsed)


def owned_lab():
    # One saved-state snapshot supplies outputs AND stable resource UUIDs. No refresh,
    # state edits, apply, or fallback to a name/numeric provider ID is needed.
    state = json.loads(run(['tofu', f'-chdir={ROOT / "opentofu"}', 'show', '-json']))
    try:
        values = state['values']
        lab = values['outputs']['lab']['value']
        nodes = lab['nodes']
        if not isinstance(nodes, dict) or not 1 <= len(nodes) <= 2:
            raise ValueError('Expected one or two state-owned nodes')
        for field in ('prefix', 'network', 'pool'):
            if not isinstance(lab[field], str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}', lab[field]):
                raise ValueError(f'Invalid saved lab {field}')
        resources = values['root_module']['resources']
        domains = {r['index']: r['values'] for r in resources
                   if r['mode'] == 'managed' and r['type'] == 'libvirt_domain' and r['name'] == 'node'}
        if set(domains) != set(nodes):
            raise ValueError('Domain resources and lab output disagree')
        if sum(r['type'] == 'libvirt_domain' for r in resources) != len(nodes):
            raise ValueError('Unexpected domain resources in project state')
        volumes = {r['address']: r['values'] for r in resources if r['type'] == 'libvirt_volume'}
        base = volumes['libvirt_volume.base']
        if (base['name'] != f"{lab['prefix']}-ubuntu-base.qcow2" or base['pool'] != lab['pool']
                or base['target']['format']['type'] != 'qcow2' or not Path(base['path']).is_absolute()):
            raise ValueError('Inconsistent saved base volume')
        uuids = set()
        for name, spec in nodes.items():
            if not re.fullmatch(r'[a-z][a-z0-9-]{0,61}[a-z0-9]', name):
                raise ValueError('Invalid saved domain name')
            domain = domains[name]
            uid = stable_uuid(domain['uuid'])
            if uid in uuids or ('uuid' in spec and stable_uuid(spec['uuid']) != uid):
                raise ValueError('Duplicate or inconsistent domain UUID in state')
            uuids.add(uid)
            # Legacy outputs contain numeric id. Ignore it, including after restart.
            spec['uuid'] = uid
            spec['base_path'] = base['path']
            if domain['name'] != name or domain['type'] != 'kvm' or domain['memory_unit'] != 'MiB':
                raise ValueError(f'{name}: inconsistent saved domain configuration')
            if any(type(spec[k]) is not int or spec[k] <= 0 for k in ('vcpu', 'memory_mib', 'disk_gib')):
                raise ValueError(f'{name}: invalid allocation in output')
            if domain['vcpu'] != spec['vcpu'] or domain['memory'] != spec['memory_mib'] or type(spec['web']) is not bool:
                raise ValueError(f'{name}: output allocation differs from domain state')
            interfaces = domain['devices']['interfaces']
            if len(interfaces) != 1 or interfaces[0]['source']['network']['network'] != lab['network']:
                raise ValueError(f'{name}: output network differs from domain state')
            for kind, suffix, fmt in (('disk', '.qcow2', 'qcow2'), ('seed', '-seed.iso', 'iso')):
                volume = volumes[f'libvirt_volume.{kind}[{json.dumps(name)}]']
                expected_name = f"{lab['prefix']}-{name}{suffix}"
                if (volume['name'] != expected_name or volume['pool'] != lab['pool']
                        or volume['target']['format']['type'] != fmt
                        or not Path(volume['path']).is_absolute()):
                    raise ValueError(f'{name}: inconsistent saved {kind} volume')
                spec[kind + '_path'] = volume['path']
                if kind == 'disk' and (spec['disk'] != expected_name or volume['capacity'] != spec['disk_gib'] * 2**30):
                    raise ValueError(f'{name}: output disk differs from volume state')
            overlay = volumes[f'libvirt_volume.disk[{json.dumps(name)}]']
            if overlay['backing_store']['path'] != base['path'] or overlay['backing_store']['format']['type'] != 'qcow2':
                raise ValueError(f'{name}: overlay backing store differs from saved base volume')
            disks = domain['devices']['disks']
            if len(disks) != 2 or {d['source']['file']['file'] for d in disks} != {spec['disk_path'], spec['seed_path']}:
                raise ValueError(f'{name}: domain disk paths differ from volume state')
        if sum(n['web'] for n in nodes.values()) != 1:
            raise ValueError('Expected exactly one web node in saved output')
        return lab
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Missing or malformed lab resource state; never guess identities') from error


class MissingLease(ValueError):
    """A boot-time condition that is safe to retry for the same verified UUID."""


def lease_address(output, mac):
    addresses = set()
    for line in output.splitlines():
        columns = line.split()
        if len(columns) == 4 and columns[1].lower() == mac.lower() and columns[2] == 'ipv4':
            addr = ipaddress.ip_interface(columns[3]).ip
            if addr.version != 4 or addr.is_loopback or addr.is_link_local or addr.is_unspecified or addr.is_multicast:
                raise ValueError('Unusable DHCP address')
            addresses.add(str(addr))
    if not addresses:
        raise MissingLease(f'No DHCP IPv4 lease for {mac}; guest may still be initializing.')
    if len(addresses) != 1:
        raise ValueError(f'Expected one DHCP IPv4 address for {mac}, found {len(addresses)}. Check boot/leases.')
    return addresses.pop()


def inspect_node(name, expected, network, require_address=True, attempts=1):
    uid = stable_uuid(expected.get('uuid'))
    if stable_uuid(virsh('domuuid', name)) != uid:
        raise ValueError(f'{name}: UUID differs from project state; refusing unrelated domain.')
    xml = ET.fromstring(virsh('dumpxml', uid))
    if xml.findtext('name') != name or stable_uuid(xml.findtext('uuid')) != uid:
        raise ValueError(f'{name}: domain XML identity differs from project state')
    interfaces = xml.findall('./devices/interface')
    if (len(interfaces) != 1 or interfaces[0].get('type') != 'network'
            or interfaces[0].find('source').get('network') != network):
        raise ValueError(f'{name}: unexpected network attachment')
    iface = interfaces[0]
    if iface.find('model').get('type') != 'virtio':
        raise ValueError(f'{name}: interface is not VirtIO')
    mac = iface.find('mac').get('address')
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', mac or ''):
        raise ValueError(f'{name}: missing or malformed interface MAC')
    state = virsh('domstate', uid)
    factors = {'KiB': 1 / 1024, 'MiB': 1, 'GiB': 1024}
    mem = xml.find('memory')
    memory = int(mem.text) * factors[mem.get('unit', 'KiB')]
    current_mem = xml.find('currentMemory')
    current_memory = (int(current_mem.text) * factors[current_mem.get('unit', 'KiB')]
                      if current_mem is not None else memory)
    cpu = xml.find('vcpu')
    vcpu = int(cpu.get('current', cpu.text))
    if (vcpu != expected['vcpu'] or int(cpu.text) != expected['vcpu']
            or memory != expected['memory_mib'] or current_memory != expected['memory_mib']):
        raise ValueError(f'{name}: runtime allocation mismatch')
    disks = xml.findall('./devices/disk')
    if len(disks) != 2:
        raise ValueError(f'{name}: unexpected disk count')
    for device, field, bus, fmt in [('disk', 'disk_path', 'virtio', 'qcow2'), ('cdrom', 'seed_path', 'sata', 'raw')]:
        matches = [d for d in disks if d.get('device') == device]
        if (len(matches) != 1 or matches[0].find('source').get('file') != expected[field]
                or matches[0].find('target').get('bus') != bus
                or matches[0].find('driver').get('type') != fmt
                or (device == 'cdrom' and matches[0].find('readonly') is None)):
            raise ValueError(f'{name}: unexpected {device} attachment')
    if require_address and state != 'running':
        raise ValueError(f'{name}: guest is {state}; no automatic restart or recreation')
    address = None
    for attempt in range(attempts):
        try:
            address = lease_address(virsh('domifaddr', uid, '--source', 'lease'), mac)
            break
        except MissingLease as error:
            if not require_address:
                break
            if attempt + 1 == attempts:
                raise MissingLease(f'{name}: {error} Inspect guest boot and DHCP; do not recreate.') from error
            time.sleep(2)
    return {'name': name, 'uuid': uid, 'state': state, 'vcpu': vcpu,
            'memory_mib': memory, 'address': address, 'mac': mac, 'xml': xml}


def inventory(lab, records):
    names = set(lab['nodes'])
    if {r['name'] for r in records} != names or len(records) != len(names):
        raise ValueError('Incomplete or duplicate discovery results')
    addresses = [r['address'] for r in records]
    if None in addresses or len(set(addresses)) != len(names):
        raise ValueError('Missing or duplicate guest addresses')
    hosts = {}
    for record in records:
        address = ipaddress.ip_address(record['address'])
        if address.version != 4 or address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
            raise ValueError('Unusable inventory address')
        if record['state'] != 'running':
            raise ValueError('Guest is not running')
        hosts[record['name']] = {'ansible_host': str(address)}
    return {'all': {'vars': {'ansible_user': 'lab', 'ansible_ssh_common_args': f'-o StrictHostKeyChecking=yes -o UserKnownHostsFile={shlex.quote(str(ROOT / ".local/known_hosts"))} '
        '-o IdentitiesOnly=yes -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no '
        '-o BatchMode=yes -o HostKeyAlgorithms=ssh-ed25519'}, 'children': {
        'lab': {'hosts': hosts},
        'web': {'hosts': {n: {} for n, spec in lab['nodes'].items() if spec['web']}}
    }}}


def overlapping_routes(network, bridge, routes):
    return [route for route in routes if route.get('dst', 'default') != 'default'
            and route.get('dev') != bridge
            and ipaddress.ip_network(route['dst'], strict=False).version == network.version
            and ipaddress.ip_network(route['dst'], strict=False).overlaps(network)]


def check_collisions(cfg, domains, volumes):
    expected_volumes = {f"{cfg['resource_prefix']}-ubuntu-base.qcow2"}
    for name in cfg['vm_names']:
        expected_volumes.update([f"{cfg['resource_prefix']}-{name}.qcow2", f"{cfg['resource_prefix']}-{name}-seed.iso"])
    if domains.intersection(cfg['vm_names']) or volumes.intersection(expected_volumes):
        raise ValueError('Names already exist. Do not overwrite/import. For an existing lab use status, verify and review a state-aware plan.')


def volume_names(output):
    lines = [line for line in output.splitlines() if line.strip()]
    if (len(lines) < 2 or lines[0].split() != ['Name', 'Path']
            or not re.fullmatch(r'[-\s]+', lines[1])):
        raise ValueError('Unexpected virsh volume-list format; cannot verify collisions.')
    names = set()
    for line in lines[2:]:
        columns = re.split(r'\s{2,}', line.strip(), maxsplit=1)
        if len(columns) != 2 or not columns[1].startswith('/') or columns[0] in names:
            raise ValueError('Cannot safely parse libvirt volume entry.')
        names.add(columns[0])
    return names


def preflight():
    required = ['virsh', 'qemu-img', 'qemu-system-x86_64', 'tofu', 'ansible-playbook', 'python3', 'git', 'ip', 'ssh-keygen']
    missing = [tool for tool in required if not shutil.which(tool)]
    if missing:
        raise ValueError('Missing tools (activate project PATH): ' + ', '.join(missing))
    if platform.machine() != 'x86_64' or 'vmx' not in Path('/proc/cpuinfo').read_text():
        raise ValueError('Expected Intel x86-64 with VT-x')
    if not os.access('/dev/kvm', os.R_OK | os.W_OK):
        raise ValueError('/dev/kvm is not accessible; owner must review KVM permissions')
    for args in [('list', '--all'), ('net-list', '--all'), ('pool-list', '--all')]:
        print(virsh(*args))
    cfg = config()
    network = cfg['network_name']
    pool = cfg['storage_pool']
    if 'Active:         yes' not in virsh('net-info', network):
        raise ValueError('Selected network is inactive. Owner must review before starting it.')
    net = ET.fromstring(virsh('net-dumpxml', network))
    forward = net.find('forward')
    if forward is None or forward.get('mode') != 'nat' or net.find('./ip/dhcp/range') is None:
        raise ValueError('Selected network must provide NAT and DHCP; owner review required.')
    routes = json.loads(run(['ip', '-j', 'route', 'show', 'table', 'all']))
    for ip in net.findall('ip'):
        subnet = ipaddress.ip_network(f"{ip.get('address')}/{ip.get('netmask') or ip.get('prefix')}", strict=False)
        if overlapping_routes(subnet, net.find('bridge').get('name'), routes):
            raise ValueError('Libvirt subnet overlaps another host route; review VPN/Docker/LAN.')
    poolxml = ET.fromstring(virsh('pool-dumpxml', pool))
    if poolxml.get('type') != 'dir' or 'State:          running' not in virsh('pool-info', pool):
        raise ValueError('Selected pool must be an active directory pool.')
    pool_info = dict(line.split(':', 1) for line in virsh('pool-info', pool, '--bytes').splitlines() if ':' in line)
    available = int(pool_info['Available'].strip())
    if available < (cfg['vm_count'] * cfg['disk_gib'] + 5) * 2**30:
        raise ValueError('Insufficient pool space for full virtual capacity plus 5 GiB reserve.')
    mem = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    if int(mem['MemAvailable'].split()[0]) < (cfg['vm_count'] * cfg['memory_mib'] + 4096) * 1024:
        raise ValueError('Insufficient available RAM: leave at least 4 GiB for the host.')
    if cfg['vm_count'] * cfg['vcpu'] > os.cpu_count() - 2:
        raise ValueError('CPU budget leaves fewer than two logical CPUs for the host.')
    key = Path(os.path.expanduser(cfg['ssh_public_key_path']))
    if not key.is_absolute():
        key = ROOT / 'opentofu' / key
    run(['ssh-keygen', '-l', '-f', str(key)])
    domains = set(virsh('list', '--all', '--name').splitlines())
    volumes = volume_names(virsh('vol-list', pool))
    # Initial deployment only: existing resources require state-aware plan review.
    check_collisions(cfg, domains, volumes)
    print('PASS: initial host preflight. Run tofu plan to enforce configuration and image guardrails.')



def agent(uid, command, arguments=None):
    request = {'execute': command}
    if arguments is not None:
        request['arguments'] = arguments
    reply = json.loads(virsh('qemu-agent-command', stable_uuid(uid), '--timeout', '5', json.dumps(request)))
    if not isinstance(reply, dict) or 'return' not in reply or 'error' in reply:
        raise ValueError(f'{uid}: guest-agent {command} failed')
    return reply['return']


def guest_exec(uid, path, arguments, attempts=30):
    pid = agent(uid, 'guest-exec', {'path': path, 'arg': arguments, 'capture-output': True})['pid']
    for attempt in range(attempts):
        response = agent(uid, 'guest-exec-status', {'pid': pid})
        if response.get('exited'):
            if response.get('out-truncated') or response.get('err-truncated') or 'exitcode' not in response:
                raise ValueError('Guest-agent command output truncated or process terminated abnormally')
            return response['exitcode'], base64.b64decode(response.get('out-data', ''), validate=True).decode()
        if attempt + 1 < attempts:
            time.sleep(1)
    raise ValueError(f'{uid}: guest-agent command timed out: {path}')


def verify_guest(uid, attempts=30):
    for attempt in range(attempts):
        try:
            agent(uid, 'guest-ping')
            break
        except ValueError as error:
            # Retry only transient agent startup. Permission, malformed protocol and
            # disabled-command errors must remain immediate failures.
            if not any(message in str(error).lower() for message in ('not connected', 'not available', 'not responding')):
                raise
            if attempt + 1 == attempts:
                raise ValueError(f'{uid}: guest agent unavailable; inspect boot/console and cloud-init logs') from error
            time.sleep(2)
    osinfo = agent(uid, 'guest-get-osinfo')
    if osinfo.get('id') != 'ubuntu' or osinfo.get('version-id') != '24.04':
        raise ValueError(f'{uid}: expected Ubuntu 24.04 guest')
    for attempt in range(attempts):
        code, output = guest_exec(uid, '/usr/bin/cloud-init', ['status', '--format', 'json'])
        status = json.loads(output)
        if code != 0 or status.get('errors') or any(status.get('recoverable_errors', {}).values()):
            raise ValueError(f'{uid}: cloud-init failed/degraded; inspect cloud-init status --long and logs via trusted agent/console')
        if status.get('status') == 'done' and status.get('extended_status', 'done') == 'done':
            return
        if status.get('status') not in ('running', 'not started'):
            raise ValueError(f'{uid}: unexpected cloud-init status: {status.get("status")}')
        if attempt + 1 < attempts:
            time.sleep(2)
    raise ValueError(f'{uid}: cloud-init incomplete after bounded wait; inspect status and logs, do not recreate')


def validated_hostkey(key):
    if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}( [^\n\r]*)?', key):
        raise ValueError('Malformed public host key')
    encoded = key.split()[1]
    wire = base64.b64decode(encoded, validate=True)
    # OpenSSH wire encoding: string algorithm, string 32-byte Ed25519 key.
    prefix = struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32)
    if len(wire) != len(prefix) + 32 or not wire.startswith(prefix):
        raise ValueError('Malformed Ed25519 public host key payload')
    return f'ssh-ed25519 {encoded}'


def guest_public_key(uid):
    code, key = guest_exec(uid, '/usr/bin/cat', ['/etc/ssh/ssh_host_ed25519_key.pub'])
    if code != 0:
        raise ValueError('Guest agent could not read public host key')
    return validated_hostkey(key.strip())


def private_write(target, content):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + '.', dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def trust_hostkeys(lab, records):
    # Recheck addresses/UUIDs before trusting keys. Match guest-reported network
    # information to the DHCP lease so an expired/reassigned lease cannot redirect SSH.
    for record in records:
        verify_guest(record['uuid'])
    confirm_agent_addresses(records)
    target = ROOT / '.local/known_hosts'
    existing = target.read_text().splitlines() if target.exists() else []
    for line in existing:
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or str(ipaddress.IPv4Address(fields[0])) != fields[0]:
            raise ValueError('Unexpected private known_hosts entry; review before updating')
        validated_hostkey(fields[1])
    additions = []
    keys = set()
    for record in records:
        uid = lab['nodes'][record['name']]['uuid']
        if record['uuid'] != uid:
            raise ValueError('Discovered UUID differs from state before host-key trust')
        key = guest_public_key(uid)
        if key in keys:
            raise ValueError('Duplicate SSH host keys across guests; investigate cloned identities')
        keys.add(key)
        address = record['address']
        previous = [line for line in existing if line.split()[0] == address]
        line = f'{address} {key}'
        if previous and previous != [line]:
            raise ValueError(f'{address}: host-key mismatch. Investigate before explicitly removing a stale key.')
        if not previous:
            additions.append(line)
    private_write(target, '\n'.join(existing + additions) + '\n')
    print(f'Public host keys verified via state UUIDs and trusted local libvirt guest-agent channel: {target}')


def confirm_agent_addresses(records):
    for record in records:
        interfaces = agent(record['uuid'], 'guest-network-get-interfaces')
        addresses = {ip['ip-address'] for iface in interfaces
                     if iface.get('hardware-address', '').lower() == record['mac'].lower()
                     for ip in iface.get('ip-addresses', []) if ip.get('ip-address-type') == 'ipv4'}
        if record['address'] not in addresses:
            raise ValueError(f'{record["name"]}: DHCP address is not confirmed by trusted guest agent')


def validate_private_inventory(lab, records, actual):
    expected = inventory(lab, records)
    if actual != expected:
        raise ValueError('Private inventory differs from freshly verified lab targets; rerun discovery and review')
    return expected


def verify_volume(spec, pool):
    path = virsh('vol-path', spec['disk'], '--pool', pool)
    vol = ET.fromstring(virsh('vol-dumpxml', spec['disk'], '--pool', pool))
    if (path != spec['disk_path'] or vol.findtext('name') != spec['disk']
            or int(vol.findtext('capacity')) != spec['disk_gib'] * 2**30
            or vol.find('target/format').get('type') != 'qcow2'
            or vol.findtext('backingStore/path') != spec['base_path']
            or vol.find('backingStore/format').get('type') != 'qcow2'):
        raise ValueError('Disk path/capacity/format/backing store differs from state')
    if int(vol.findtext('allocation')) >= int(vol.findtext('capacity')):
        raise ValueError('Thin allocation not observed; inspect pool support')
    print(f"  disk capacity={vol.findtext('capacity')} bytes; allocation={vol.findtext('allocation')} bytes")


def verify_environment(lab):
    if 'Active:         yes' not in virsh('net-info', lab['network']):
        raise ValueError('Selected lab network is inactive; owner review required')
    net = ET.fromstring(virsh('net-dumpxml', lab['network']))
    forward = net.find('forward')
    if forward is None or forward.get('mode') != 'nat':
        raise ValueError('Selected lab network must remain NAT')
    ranges = [(ipaddress.IPv4Address(r.get('start')), ipaddress.IPv4Address(r.get('end')))
              for r in net.findall('./ip/dhcp/range') if ':' not in r.get('start', '')]
    if not ranges or any(start > end for start, end in ranges):
        raise ValueError('Selected lab network has no usable DHCP range')
    if 'State:          running' not in virsh('pool-info', lab['pool']):
        raise ValueError('Selected lab storage pool is inactive; owner review required')
    pool = ET.fromstring(virsh('pool-dumpxml', lab['pool']))
    if pool.get('type') != 'dir':
        raise ValueError('Selected lab storage pool must remain a directory pool')
    for spec in lab['nodes'].values():
        if any(str(Path(spec[k]).parent) != pool.findtext('target/path') for k in ('disk_path', 'seed_path', 'base_path')):
            raise ValueError('Saved volume paths differ from the selected pool directory')
    return ranges


def validate_lease_ranges(records, ranges):
    for record in records:
        if record['address'] is not None:
            address = ipaddress.IPv4Address(record['address'])
            if not any(start <= address <= end for start, end in ranges):
                raise ValueError(f'{record["name"]}: discovered address is outside selected NAT DHCP ranges')


def validate_idempotency(stats, names):
    if not isinstance(stats, dict) or set(stats) - {'localhost'} != set(names):
        raise ValueError('Idempotency recap is missing expected guests or includes unexpected hosts')
    for host, summary in stats.items():
        if not isinstance(summary, dict) or any(type(summary.get(k)) is not int or summary[k] != 0
                                                for k in ('changed', 'failures', 'unreachable')):
            raise ValueError(f'Idempotency FAILED: {host}: {summary}')
        if type(summary.get('ok')) is not int or summary['ok'] <= 0:
            raise ValueError(f'Idempotency recap has no successful tasks for {host}')
    print('PASS: second real configuration run reported zero changes/failures/unreachable hosts for every expected guest.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['preflight', 'discover', 'status', 'verify', 'trust-hostkeys', 'check-inventory', 'check-idempotency'])
    args = parser.parse_args()
    if args.command == 'preflight':
        preflight()
        return
    lab = owned_lab()
    if args.command == 'check-idempotency':
        validate_idempotency(json.loads((ROOT / '.local/idempotency.json').read_text()), lab['nodes'])
        return
    ranges = verify_environment(lab)
    records = [inspect_node(n, spec, lab['network'], args.command != 'status', attempts=30)
               for n, spec in lab['nodes'].items()]
    validate_lease_ranges(records, ranges)
    if args.command == 'trust-hostkeys':
        trust_hostkeys(lab, records)
    elif args.command == 'discover':
        target = ROOT / '.local/inventory.json'
        private_write(target, json.dumps(inventory(lab, records), indent=2) + '\n')
        print(target)
    elif args.command == 'check-inventory':
        # Used by every playbook before facts or remote tasks. Never trust stale or
        # expanded inventory, including extra host/group/connection variables.
        confirm_agent_addresses(records)
        actual = json.loads((ROOT / '.local/inventory.json').read_text())
        print(json.dumps(validate_private_inventory(lab, records, actual)))
    else:
        for record in records:
            name = record['name']
            print(f"{name}: {record['state']}; {record['vcpu']} vCPU / {record['memory_mib']:g} MiB; IPv4 {record['address'] or 'unavailable'}")
            if args.command == 'verify':
                spec = lab['nodes'][name]
                verify_volume(spec, lab['pool'])
                if int(virsh('vcpucount', record['uuid'], '--live', '--active')) != spec['vcpu']:
                    raise ValueError(f'{name}: live vCPU allocation mismatch')
                verify_guest(record['uuid'])
                confirm_agent_addresses([record])
                print('  PASS: UUID, allocations, disks, network, Ubuntu 24.04, guest agent and cloud-init done')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, ET.ParseError, AttributeError, subprocess.TimeoutExpired) as error:
        sys.exit(f'ERROR: {error}')
