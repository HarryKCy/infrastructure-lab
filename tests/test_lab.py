import importlib.util
import ipaddress
import base64
import copy
import json
import struct
from pathlib import Path
import subprocess
from unittest.mock import patch
import pytest

spec = importlib.util.spec_from_file_location('lab', Path(__file__).resolve().parents[1] / 'scripts/lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)
MAC = '52:54:00:12:34:56'
UID = '12345678-1234-4234-8234-123456789abc'
OTHER_UID = '87654321-4321-4321-8321-cba987654321'
KEY = 'ssh-ed25519 ' + base64.b64encode(struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32) + bytes(range(32))).decode()
OTHER_KEY = 'ssh-ed25519 ' + base64.b64encode(struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32) + bytes(range(1, 33))).decode()


def test_lease():
    assert lab.lease_address(f'vnet0 {MAC} ipv4 192.0.2.10/24', MAC) == '192.0.2.10'


@pytest.mark.parametrize('data', ['', 'malformed', f'vnet0 {MAC} ipv4 127.0.0.1/8',
                                  f'vnet0 {MAC} ipv4 invalid',
                                  f'vnet0 {MAC} ipv4 192.0.2.10/24\nvnet0 {MAC} ipv4 192.0.2.11/24'])
def test_bad_lease(data):
    with pytest.raises(ValueError):
        lab.lease_address(data, MAC)


def test_only_matching_mac():
    with pytest.raises(ValueError):
        lab.lease_address('vnet0 52:54:00:00:00:00 ipv4 192.0.2.1/24', MAC)


def test_inventory():
    result = lab.inventory({'nodes': {'node': {'web': True}}},
                           [{'name': 'node', 'address': '192.0.2.2', 'state': 'running'}])
    assert result['all']['children']['web']['hosts'] == {'node': {}}
    assert result['all']['vars']['ansible_user'] == 'lab'


@pytest.mark.parametrize('records', [[], [{'name': 'wrong', 'address': '192.0.2.2', 'state': 'running'}],
                                     [{'name': 'node', 'address': None, 'state': 'running'}],
                                     [{'name': 'node', 'address': 'bad', 'state': 'running'}],
                                     [{'name': 'node', 'address': '192.0.2.2', 'state': 'shut off'}]])
def test_bad_inventory(records):
    with pytest.raises(ValueError):
        lab.inventory({'nodes': {'node': {'web': True}}}, records)


def test_duplicate_inventory():
    with pytest.raises(ValueError):
        lab.inventory({'nodes': {'a': {'web': False}, 'b': {'web': True}}},
                      [{'name': n, 'address': '192.0.2.2', 'state': 'running'} for n in ['a', 'b']])


def test_route_overlap():
    network = ipaddress.ip_network('192.168.122.0/24')
    assert not lab.overlapping_routes(network, 'virbr0', [{'dst': '192.168.122.0/24', 'dev': 'virbr0'}])
    assert lab.overlapping_routes(network, 'virbr0', [{'dst': '192.168.0.0/16', 'dev': 'tun0'}])
    assert not lab.overlapping_routes(network, 'virbr0', [{'dst': 'default', 'dev': 'wlan0'}])


def test_command_failure_not_swallowed():
    with patch.object(lab.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'permission denied')):
        with pytest.raises(ValueError, match='permission denied'):
            lab.virsh('list', '--all')


def test_explicit_system_connection_no_shell():
    with patch.object(lab.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'ok', '')) as mock:
        assert lab.virsh('domuuid', 'node; malicious') == 'ok'
        assert mock.call_args.args[0] == ['virsh', '-c', 'qemu:///system', 'domuuid', 'node; malicious']
        assert 'shell' not in mock.call_args.kwargs


def test_uuid_mismatch():
    with patch.object(lab, 'virsh', return_value=OTHER_UID):
        with pytest.raises(ValueError, match='UUID differs'):
            lab.inspect_node('node', {'uuid': UID}, 'default')


def test_bad_json_output():
    with patch.object(lab, 'run', return_value='not json'):
        with pytest.raises(ValueError):
            lab.owned_lab()


def test_hostkey_read():
    import base64
    key = KEY + ' guest'
    with patch.object(lab, 'virsh', side_effect=['{"return":{"pid":9}}',
                      __import__('json').dumps({'return': {'exited': True, 'exitcode': 0,
                                                           'out-data': base64.b64encode(key.encode()).decode()}})]):
        assert lab.guest_public_key(UID) == ' '.join(key.split()[:2])


def test_hostkey_failed_read():
    with patch.object(lab, 'virsh', side_effect=['{"return":{"pid":9}}',
                      '{"return":{"exited":true,"exitcode":1}}']):
        with pytest.raises(ValueError, match='could not read'):
            lab.guest_public_key(UID)


def test_hostkey_mismatch(tmp_path):
    (tmp_path / '.local').mkdir()
    (tmp_path / '.local/known_hosts').write_text(f'192.0.2.2 {KEY}\n')
    with patch.object(lab, 'verify_guest'), patch.object(lab, 'confirm_agent_addresses'), patch.object(lab, 'ROOT', tmp_path), patch.object(lab, 'guest_public_key', return_value=OTHER_KEY):
        with pytest.raises(ValueError, match='mismatch'):
            lab.trust_hostkeys({'nodes': {'node': {'uuid': UID}}}, [{'name': 'node', 'uuid': UID, 'address': '192.0.2.2'}])
    assert KEY in (tmp_path / '.local/known_hosts').read_text()


def test_hostkey_trust_is_repeatable(tmp_path):
    with patch.object(lab, 'verify_guest'), patch.object(lab, 'confirm_agent_addresses'), patch.object(lab, 'ROOT', tmp_path), patch.object(lab, 'guest_public_key', return_value=KEY):
        for _ in range(2):
            lab.trust_hostkeys({'nodes': {'node': {'uuid': UID}}}, [{'name': 'node', 'uuid': UID, 'address': '192.0.2.2'}])
    assert (tmp_path / '.local/known_hosts').read_text() == f'192.0.2.2 {KEY}\n'


def test_workflow_safety():
    import yaml
    workflow = yaml.safe_load((lab.ROOT / '.github/workflows/validate.yml').read_text())
    assert workflow['permissions'] == {'contents': 'read'}
    for job in workflow['jobs'].values():
        assert job['timeout-minutes'] <= 15
        for step in job['steps']:
            if 'uses' in step:
                assert __import__('re').fullmatch(r'.+@[0-9a-f]{40}', step['uses'])
            assert not __import__('re').search(r'\btofu\s+(apply|destroy)\b', step.get('run', ''))


@pytest.mark.parametrize('domains,volumes', [({'node'}, set()),
                                           (set(), {'prefix-node.qcow2'}),
                                           (set(), {'prefix-ubuntu-base.qcow2'})])
def test_preexisting_resources_rejected(domains, volumes):
    with pytest.raises(ValueError, match='Names already exist'):
        lab.check_collisions({'resource_prefix': 'prefix', 'vm_names': ['node']}, domains, volumes)


def test_unrelated_names_allowed():
    lab.check_collisions({'resource_prefix': 'prefix', 'vm_names': ['node']}, {'other'}, {'other.qcow2'})


def state_fixture(runtime_id=2, output_uuid=False):
    """Provider 0.9.9 shape, synthetic identities/paths only."""
    node = {'id': runtime_id, 'vcpu': 2, 'memory_mib': 3072, 'disk_gib': 30,
            'disk': 'prefix-node.qcow2', 'web': True}
    if output_uuid:
        node['uuid'] = UID
    spec = {'uuid': UID, 'vcpu': 2, 'memory_mib': 3072, 'disk_gib': 30,
            'base_path': '/lab/prefix-ubuntu-base.qcow2',
            'disk': node['disk'], 'disk_path': '/lab/prefix-node.qcow2', 'seed_path': '/lab/prefix-node-seed.iso'}
    domain = {'id': runtime_id, 'uuid': UID, 'name': 'node', 'type': 'kvm', 'memory_unit': 'MiB',
              'vcpu': 2, 'memory': 3072, 'devices': {
                  'interfaces': [{'source': {'network': {'network': 'default'}}}],
                  'disks': [{'source': {'file': {'file': spec[k]}}} for k in ['disk_path', 'seed_path']]}}
    resources = [{'address': 'libvirt_domain.node["node"]', 'mode': 'managed', 'type': 'libvirt_domain',
                  'name': 'node', 'index': 'node', 'values': domain}]
    for kind, suffix, fmt in [('disk', '.qcow2', 'qcow2'), ('seed', '-seed.iso', 'iso')]:
        resources.append({'address': f'libvirt_volume.{kind}["node"]', 'mode': 'managed', 'type': 'libvirt_volume',
                          'name': kind, 'index': 'node', 'values': {
                              'name': f'prefix-node{suffix}', 'pool': 'pool', 'path': spec[kind + '_path'],
                              'capacity': 30 * 2**30 if kind == 'disk' else 45056, 'target': {'format': {'type': fmt}}}})
    resources[1]['values']['backing_store'] = {'path': spec['base_path'], 'format': {'type': 'qcow2'}}
    resources.append({'address': 'libvirt_volume.base', 'mode': 'managed', 'type': 'libvirt_volume',
                      'name': 'base', 'values': {'name': 'prefix-ubuntu-base.qcow2', 'pool': 'pool',
                                              'path': spec['base_path'], 'target': {'format': {'type': 'qcow2'}}}})
    return {'values': {'outputs': {'lab': {'value': {'nodes': {'node': node}, 'network': 'default',
                                                   'pool': 'pool', 'prefix': 'prefix'}}},
                       'root_module': {'resources': resources}}}, spec


def xml_fixture(runtime_id=2):
    return f'''<domain type="kvm" id="{runtime_id}"><name>node</name><uuid>{UID}</uuid>
    <vcpu>2</vcpu><memory unit="KiB">3145728</memory><currentMemory unit="KiB">3145728</currentMemory>
    <devices><interface type="network"><source network="default"/><model type="virtio"/>
    <mac address="{MAC}"/></interface>
    <disk device="disk"><source file="/lab/prefix-node.qcow2"/><target bus="virtio"/><driver type="qcow2"/></disk>
    <disk device="cdrom"><source file="/lab/prefix-node-seed.iso"/><target bus="sata"/><driver type="raw"/><readonly/></disk>
    </devices></domain>'''


def virsh_fixture(xml=None, leases=None):
    def call(command, *args):
        if command == 'domuuid':
            assert args == ('node',)
            return UID
        assert args[0] == UID, 'All subsequent domain queries must use the verified stable UUID'
        return {'dumpxml': xml or xml_fixture(), 'domstate': 'running',
                'domifaddr': leases if leases is not None else f'vnet9 {MAC} ipv4 192.0.2.10/24'}[command]
    return call


@pytest.mark.parametrize('runtime_id', [1, 2, 999, '27', None])
@pytest.mark.parametrize('output_uuid', [False, True])
def test_saved_uuid_ignores_numeric_ids(runtime_id, output_uuid):
    state, _ = state_fixture(runtime_id, output_uuid)
    with patch.object(lab, 'run', return_value=json.dumps(state)) as run:
        result = lab.owned_lab()
    assert result['nodes']['node']['uuid'] == UID
    assert run.call_args.args[0][-2:] == ['show', '-json']


@pytest.mark.parametrize('value', [None, '', 2, '2', 'not-a-uuid', '00000000-0000-0000-0000-000000000000',
                                   '12345678123442348234123456789abc'])
def test_invalid_uuid_fails_before_hypervisor(value):
    with patch.object(lab, 'virsh') as virsh:
        with pytest.raises(ValueError, match='UUID'):
            lab.inspect_node('node', {'uuid': value}, 'default')
        virsh.assert_not_called()


def test_missing_resource_uuid_never_uses_output_id():
    state, _ = state_fixture()
    del state['values']['root_module']['resources'][0]['values']['uuid']
    with patch.object(lab, 'run', return_value=json.dumps(state)):
        with pytest.raises(ValueError, match='state'):
            lab.owned_lab()


@pytest.mark.parametrize('defect', ['uuid', 'allocation', 'name', 'disk', 'iso', 'network', 'missing-domain', 'extra-domain'])
def test_inconsistent_state(defect):
    state, _ = state_fixture(output_uuid=True)
    resources = state['values']['root_module']['resources']
    domain = resources[0]['values']
    if defect == 'uuid':
        domain['uuid'] = OTHER_UID
    elif defect == 'allocation':
        domain['vcpu'] = 4
    elif defect == 'name':
        domain['name'] = 'unrelated'
    elif defect == 'disk':
        resources[1]['values']['path'] = '/lab/unrelated.qcow2'
    elif defect == 'iso':
        resources[2]['values']['target']['format']['type'] = 'qcow2'
    elif defect == 'network':
        domain['devices']['interfaces'][0]['source']['network']['network'] = 'public'
    elif defect == 'missing-domain':
        resources.pop(0)
    else:
        extra = copy.deepcopy(resources[0]); extra['index'] = 'other'; resources.append(extra)
    with patch.object(lab, 'run', return_value=json.dumps(state)):
        with pytest.raises(ValueError):
            lab.owned_lab()


def test_restart_preserves_uuid_and_discovery():
    for runtime_id in (2, 19):
        _, spec = state_fixture(runtime_id)
        spec['id'] = runtime_id
        with patch.object(lab, 'virsh', side_effect=virsh_fixture(xml_fixture(runtime_id))):
            record = lab.inspect_node('node', spec, 'default')
        assert (record['uuid'], record['address']) == (UID, '192.0.2.10')


@pytest.mark.parametrize('old,new', [('3145728', '1048576'), ('<vcpu>2', '<vcpu>4'),
                                   ('<vcpu>2', '<vcpu current="1">2'), ('network="default"', 'network="public"'),
                                   ('prefix-node.qcow2', 'unrelated.qcow2'), ('<readonly/>', ''),
                                   ('<uuid>' + UID, '<uuid>' + OTHER_UID)])
def test_incorrect_runtime_allocation_or_attachments(old, new):
    _, spec = state_fixture()
    with patch.object(lab, 'virsh', side_effect=virsh_fixture(xml_fixture().replace(old, new))):
        with pytest.raises(ValueError):
            lab.inspect_node('node', spec, 'default')


def test_missing_lease_bounded_retry():
    _, spec = state_fixture()
    counter = iter(['', f'vnet0 {MAC} ipv4 192.0.2.10/24'])
    base = virsh_fixture()
    with patch.object(lab, 'virsh', side_effect=lambda cmd, *args: next(counter) if cmd == 'domifaddr' else base(cmd, *args)), \
            patch.object(lab.time, 'sleep') as sleep:
        assert lab.inspect_node('node', spec, 'default', attempts=2)['address'] == '192.0.2.10'
        sleep.assert_called_once_with(2)


def test_missing_lease_timeout_and_status():
    _, spec = state_fixture()
    with patch.object(lab, 'virsh', side_effect=virsh_fixture(leases='')), patch.object(lab.time, 'sleep') as sleep:
        with pytest.raises(lab.MissingLease, match='do not recreate'):
            lab.inspect_node('node', spec, 'default', attempts=3)
        assert sleep.call_count == 2
        assert lab.inspect_node('node', spec, 'default', require_address=False)['address'] is None


def test_ambiguous_lease_not_retried():
    _, spec = state_fixture()
    leases = f'vnet0 {MAC} ipv4 192.0.2.10/24\nvnet0 {MAC} ipv4 192.0.2.11/24'
    with patch.object(lab, 'virsh', side_effect=virsh_fixture(leases=leases)), patch.object(lab.time, 'sleep') as sleep:
        with pytest.raises(ValueError, match='found 2'):
            lab.inspect_node('node', spec, 'default', attempts=30)
        sleep.assert_not_called()


@pytest.mark.parametrize('body,expected', [('', set()),
                                         (' prefix-node.qcow2   /lab/prefix-node.qcow2\n', {'prefix-node.qcow2'}),
                                         (' name with spaces  /lab/name with spaces\n', {'name with spaces'})])
def test_volume_list_table(body, expected):
    assert lab.volume_names(' Name     Path\n ---------------------------\n' + body) == expected


@pytest.mark.parametrize('output', ['', 'Name Path\nNOT A SEPARATOR', 'Name Path\n---\nambiguous /path',
                                    'Name Path\n---\nname  relative/path', 'Name Path\n---\na  /a\na  /b'])
def test_malformed_volume_list_fails_closed(output):
    with pytest.raises(ValueError):
        lab.volume_names(output)


def test_volume_parser_keeps_seed_collision_protection():
    volumes = lab.volume_names('Name Path\n----------\nprefix-node-seed.iso  /pool/prefix-node-seed.iso')
    with pytest.raises(ValueError, match='Names already exist'):
        lab.check_collisions({'resource_prefix': 'prefix', 'vm_names': ['node']}, set(), volumes)


@pytest.mark.parametrize('reply', ['{}', '{"error":{"desc":"disabled"}}', 'not-json', '[]'])
def test_guest_agent_protocol_failures(reply):
    with patch.object(lab, 'virsh', return_value=reply):
        with pytest.raises(ValueError):
            lab.agent(UID, 'guest-ping')


def test_guest_agent_failure_not_swallowed():
    with patch.object(lab, 'virsh', side_effect=ValueError('permission denied')), patch.object(lab.time, 'sleep') as sleep:
        with pytest.raises(ValueError, match='permission denied'):
            lab.verify_guest(UID)
        sleep.assert_not_called()


def test_agent_startup_timeout():
    with patch.object(lab, 'agent', side_effect=ValueError('not connected')), patch.object(lab.time, 'sleep') as sleep:
        with pytest.raises(ValueError, match='agent unavailable'):
            lab.verify_guest(UID, attempts=3)
        assert sleep.call_count == 2


@pytest.mark.parametrize('status,code', [({'status': 'error'}, 1), ({'status': 'done'}, 2),
                                       ({'status': 'done', 'errors': ['failed']}, 0),
                                       ({'status': 'done', 'recoverable_errors': {'WARNING': ['failed']}}, 0),
                                       ({'status': 'disabled'}, 0), ({'status': 'running'}, 0)])
def test_cloud_init_failure_or_incomplete(status, code):
    with patch.object(lab, 'agent', side_effect=[{}, {'id': 'ubuntu', 'version-id': '24.04'}]), \
            patch.object(lab, 'guest_exec', return_value=(code, json.dumps(status))):
        with pytest.raises(ValueError, match='cloud-init'):
            lab.verify_guest(UID, attempts=1)


def test_cloud_init_completion_after_wait():
    with patch.object(lab, 'agent', side_effect=[{}, {'id': 'ubuntu', 'version-id': '24.04'}]), \
            patch.object(lab, 'guest_exec', side_effect=[(0, '{"status":"running"}'), (0, '{"status":"done"}')]), \
            patch.object(lab.time, 'sleep') as sleep:
        lab.verify_guest(UID, attempts=2)
        sleep.assert_called_once_with(2)


@pytest.mark.parametrize('key', ['ssh-ed25519 !!!', 'ssh-rsa AAAA', 'ssh-ed25519 AAAA', KEY + '\n' + KEY])
def test_malformed_host_keys_rejected(key):
    with pytest.raises(ValueError):
        lab.validated_hostkey(key)


def test_hostkey_command_timeout():
    with patch.object(lab, 'agent', side_effect=[{'pid': 1}, {'exited': False}]), patch.object(lab.time, 'sleep'):
        with pytest.raises(ValueError, match='timed out'):
            lab.guest_exec(UID, '/usr/bin/cat', ['/etc/ssh/ssh_host_ed25519_key.pub'], attempts=1)


@pytest.mark.parametrize('response', [{'exited': True, 'exitcode': 0, 'out-truncated': True},
                                     {'exited': True, 'signal': 9}])
def test_guest_command_incomplete_output(response):
    with patch.object(lab, 'agent', side_effect=[{'pid': 1}, response]):
        with pytest.raises(ValueError):
            lab.guest_exec(UID, '/usr/bin/cat', [])


def test_agent_must_confirm_address():
    record = {'uuid': UID, 'name': 'node', 'mac': MAC, 'address': '192.0.2.10'}
    with patch.object(lab, 'agent', return_value=[{'hardware-address': MAC, 'ip-addresses': [
            {'ip-address-type': 'ipv4', 'ip-address': '192.0.2.11'}]}]):
        with pytest.raises(ValueError, match='not confirmed'):
            lab.confirm_agent_addresses([record])


@pytest.mark.parametrize('defect', ['extra-host', 'address', 'connection', 'web', 'user'])
def test_unexpected_private_inventory(defect):
    owned = {'nodes': {'node': {'web': True}}}
    records = [{'name': 'node', 'address': '192.0.2.2', 'state': 'running'}]
    actual = lab.inventory(owned, records)
    if defect == 'extra-host':
        actual['all']['children']['lab']['hosts']['unrelated'] = {'ansible_host': '192.0.2.99'}
    elif defect == 'address':
        actual['all']['children']['lab']['hosts']['node']['ansible_host'] = '192.0.2.99'
    elif defect == 'connection':
        actual['all']['vars']['ansible_connection'] = 'local'
    elif defect == 'web':
        actual['all']['children']['web']['hosts'] = {}
    else:
        actual['all']['vars']['ansible_user'] = 'root'
    with pytest.raises(ValueError, match='inventory differs'):
        lab.validate_private_inventory(owned, records, actual)


def test_atomic_private_write_permissions_and_symlink(tmp_path):
    target = tmp_path / 'inventory.json'
    unrelated = tmp_path / 'unrelated'
    unrelated.write_text('untouched')
    target.symlink_to(unrelated)
    lab.private_write(target, '{}\n')
    assert unrelated.read_text() == 'untouched'
    assert not target.is_symlink()
    assert target.stat().st_mode & 0o777 == 0o600


def test_idempotency_success():
    lab.validate_idempotency({'node': {'changed': 0, 'failures': 0, 'unreachable': 0, 'ok': 10},
                              'localhost': {'changed': 0, 'failures': 0, 'unreachable': 0, 'ok': 4}}, ['node'])


@pytest.mark.parametrize('stats', [{}, {'localhost': {'ok': 4, 'changed': 0, 'failures': 0, 'unreachable': 0}},
                                   {'other': {'ok': 4, 'changed': 0, 'failures': 0, 'unreachable': 0}},
                                   *[{'node': {'ok': 10, 'changed': 0, 'failures': 0, 'unreachable': 0, **override}}
                                     for override in [{'changed': 1}, {'failures': 1}, {'unreachable': 1},
                                                      {'changed': False}, {'ok': 0}]]])
def test_idempotency_failure_or_missing_hosts(stats):
    with pytest.raises(ValueError, match='Idempotency'):
        lab.validate_idempotency(stats, ['node'])


@pytest.mark.parametrize('flag', ['--check', '-C', '--limit', '--tags', '--inventory', '--syntax-check'])
def test_idempotency_rejects_non_execution_flags(flag):
    result = subprocess.run(['bash', str(lab.ROOT / 'scripts/check-idempotency.sh'), flag],
                            capture_output=True, text=True, cwd=lab.ROOT)
    assert result.returncode == 2
    assert 'unsupported idempotency argument' in result.stderr


def test_callback_preserves_real_changes(tmp_path, monkeypatch):
    callback_spec = importlib.util.spec_from_file_location('lab_stats', lab.ROOT / 'ansible/callback_plugins/lab_stats.py')
    callback = importlib.util.module_from_spec(callback_spec)
    callback_spec.loader.exec_module(callback)
    from unittest.mock import Mock
    stats = Mock(processed={'node': 1})
    stats.summarize.return_value = {'changed': 3, 'failures': 0, 'unreachable': 0, 'ok': 10}
    target = tmp_path / 'stats.json'
    monkeypatch.setenv('LAB_STATS_FILE', str(target))
    callback.CallbackModule().v2_playbook_on_stats(stats)
    assert json.loads(target.read_text())['node']['changed'] == 3
    assert target.stat().st_mode & 0o777 == 0o600


def test_application_failure_conditions_with_real_ansible(tmp_path):
    """Evaluate the actual playbook/role conditions with Ansible and synthetic HTTP responses."""
    import yaml
    role = yaml.safe_load((lab.ROOT / 'ansible/roles/webserver/tasks/main.yml').read_text())
    verify = yaml.safe_load((lab.ROOT / 'ansible/playbooks/verify.yml').read_text())
    conditions = [role[-1]['failed_when'], verify[-1]['tasks'][0]['failed_when']]
    good = {'status': 200, 'content': 'Infrastructure Lab - OK\n', 'x_infrastructure_lab_node': 'localhost'}
    fixtures = [(good, False), ({**good, 'status': 503}, True), ({**good, 'content': 'wrong'}, True),
                ({**good, 'x_infrastructure_lab_node': 'unrelated'}, True),
                ({'status': 200, 'content': good['content']}, True)]
    tasks = []
    for condition in conditions:
        for health, failed in fixtures:
            tasks.append({'name': 'Evaluate actual health acceptance expression',
                          'ansible.builtin.assert': {'that': [f'({condition}) == expected_failure']},
                          'vars': {'health': health, 'expected_failure': failed}})
    playbook = tmp_path / 'health-fixtures.yml'
    playbook.write_text(yaml.safe_dump([{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False, 'tasks': tasks}]))
    result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(playbook)],
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('mode,pool_type', [('nat', 'dir'), ('bridge', 'dir'), ('nat', 'logical')])
def test_selected_network_and_pool_validation(mode, pool_type):
    _, spec = state_fixture()
    owned = {'network': 'default', 'pool': 'pool', 'nodes': {'node': spec}}
    outputs = {'net-info': 'Active:         yes',
               'net-dumpxml': f'<network><forward mode="{mode}"/><ip><dhcp><range start="192.0.2.2" end="192.0.2.100"/></dhcp></ip></network>',
               'pool-info': 'State:          running',
               'pool-dumpxml': f'<pool type="{pool_type}"><target><path>/lab</path></target></pool>'}
    with patch.object(lab, 'virsh', side_effect=lambda cmd, name: outputs[cmd]):
        if mode == 'nat' and pool_type == 'dir':
            ranges = lab.verify_environment(owned)
            lab.validate_lease_ranges([{'name': 'node', 'address': '192.0.2.10'}], ranges)
            with pytest.raises(ValueError, match='outside'):
                lab.validate_lease_ranges([{'name': 'node', 'address': '198.51.100.10'}], ranges)
        else:
            with pytest.raises(ValueError):
                lab.verify_environment(owned)


@pytest.mark.parametrize('defect', [None, 'extra-host', 'address', 'connection', 'extra-group', 'user'])
def test_effective_ansible_guard_before_remote_access(tmp_path, defect):
    """Exercise the real guard with a synthetic local discovery command. No SSH or libvirt."""
    import yaml
    root = tmp_path / 'project'
    plays = root / 'ansible/playbooks'
    plays.mkdir(parents=True)
    (root / 'scripts').mkdir()
    canonical = lab.inventory({'nodes': {'node': {'web': True}}},
                              [{'name': 'node', 'state': 'running', 'address': '192.0.2.2'}])
    # Only the discovery subprocess is replaced. The guard's actual assertions run.
    (root / 'scripts/lab.py').write_text('print(' + repr(json.dumps(canonical)) + ')\n')
    guard = plays / 'guard.yml'
    guard.write_text((lab.ROOT / 'ansible/playbooks/guard.yml').read_text())
    actual = copy.deepcopy(canonical)
    hosts = actual['all']['children']['lab']['hosts']
    if defect == 'extra-host':
        hosts['unrelated'] = {'ansible_host': '192.0.2.99'}
    elif defect == 'address':
        hosts['node']['ansible_host'] = '192.0.2.99'
    elif defect == 'connection':
        hosts['node']['ansible_connection'] = 'local'
    elif defect == 'extra-group':
        actual['all']['children']['unrelated'] = {'hosts': {'node': {}}}
    elif defect == 'user':
        actual['all']['vars']['ansible_user'] = 'root'
    inventory_path = root / 'inventory.yml'
    inventory_path.write_text(yaml.safe_dump(actual))
    result = subprocess.run(['ansible-playbook', '-i', str(inventory_path), str(guard)],
                            capture_output=True, text=True, timeout=60)
    assert (result.returncode == 0) == (defect is None), result.stdout + result.stderr
    assert 'Gathering Facts' not in result.stdout


def test_unrelated_backing_volume_in_saved_state_rejected():
    state, _ = state_fixture()
    state['values']['root_module']['resources'][1]['values']['backing_store']['path'] = '/unrelated/base.qcow2'
    with patch.object(lab, 'run', return_value=json.dumps(state)):
        with pytest.raises(ValueError, match='backing store'):
            lab.owned_lab()


@pytest.mark.parametrize('defect', [None, 'capacity', 'format', 'backing', 'path'])
def test_actual_volume_configuration(defect, capsys):
    _, spec = state_fixture()
    xml = f'''<volume><name>{spec['disk']}</name><capacity>{30 * 2**30}</capacity><allocation>200704</allocation>
    <target><format type="qcow2"/></target><backingStore><path>{spec['base_path']}</path>
    <format type="qcow2"/></backingStore></volume>'''
    path = spec['disk_path']
    if defect == 'capacity':
        xml = xml.replace(str(30 * 2**30), str(10 * 2**30))
    elif defect == 'format':
        xml = xml.replace('qcow2', 'raw')
    elif defect == 'backing':
        xml = xml.replace(spec['base_path'], '/unrelated/base.qcow2')
    elif defect == 'path':
        path = '/unrelated/disk.qcow2'
    with patch.object(lab, 'virsh', side_effect=[path, xml]):
        if defect is None:
            lab.verify_volume(spec, 'pool')
            assert 'allocation=200704 bytes' in capsys.readouterr().out
        else:
            with pytest.raises(ValueError):
                lab.verify_volume(spec, 'pool')


def test_hostkey_update_is_transactional_on_second_guest_failure(tmp_path):
    records = [{'name': name, 'uuid': uid, 'address': ip} for name, uid, ip in
               [('node', UID, '192.0.2.10'), ('other', OTHER_UID, '192.0.2.11')]]
    owned = {'nodes': {r['name']: {'uuid': r['uuid']} for r in records}}
    with patch.object(lab, 'ROOT', tmp_path), patch.object(lab, 'verify_guest'), \
            patch.object(lab, 'confirm_agent_addresses'), \
            patch.object(lab, 'guest_public_key', side_effect=[KEY, ValueError('agent failed')]):
        with pytest.raises(ValueError, match='agent failed'):
            lab.trust_hostkeys(owned, records)
    assert not (tmp_path / '.local/known_hosts').exists()


def test_cloned_host_keys_rejected(tmp_path):
    records = [{'name': name, 'uuid': uid, 'address': ip} for name, uid, ip in
               [('node', UID, '192.0.2.10'), ('other', OTHER_UID, '192.0.2.11')]]
    owned = {'nodes': {r['name']: {'uuid': r['uuid']} for r in records}}
    with patch.object(lab, 'ROOT', tmp_path), patch.object(lab, 'verify_guest'), \
            patch.object(lab, 'confirm_agent_addresses'), patch.object(lab, 'guest_public_key', return_value=KEY):
        with pytest.raises(ValueError, match='Duplicate SSH host keys'):
            lab.trust_hostkeys(owned, records)
    assert not (tmp_path / '.local/known_hosts').exists()
