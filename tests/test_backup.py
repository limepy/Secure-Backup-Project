import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backup as app


@pytest.fixture
def data(tmp_path):
    source, output, keys = (tmp_path / name for name in ('source', 'backups', 'keys'))
    source.mkdir()
    (source / 'file.txt').write_text('Critical data', encoding='utf-8')
    (source / 'empty').mkdir()
    app.init_keys(keys)
    return source, output, keys


def test_restore(data, tmp_path):
    source, output, keys = data
    assert 'BACKUP_OK' in app.backup(source, output, keys)
    version = next((output / source.name / '1').glob('backup-*'))
    target = tmp_path / 'restored'
    target.mkdir()
    assert 'RESTORE_OK' in app.restore(version, target, keys)
    assert app.manifest(source) == app.manifest(target)


def test_corrupted_byte(data, tmp_path, capsys, monkeypatch):
    source, output, keys = data
    app.backup(source, output, keys)
    version = next((output / source.name / '1').glob('backup-*'))
    archive = version / 'archive.enc'
    with archive.open('r+b') as stream:
        stream.seek(100)
        byte = stream.read(1)
        stream.seek(100)
        stream.write(bytes([byte[0] ^ 1]))
    target = tmp_path / 'restored'
    monkeypatch.setattr(app, 'require_root', lambda: None)
    code = app.main(['restore', '--output', str(output), '--project', source.name,
                     '--version', '1', '--keys', str(keys), '--target', str(target),
                     '--log', str(tmp_path / 'test.log')])
    assert code == 1
    assert 'before restoration' in capsys.readouterr().out
    assert not target.exists()


def test_missing_key(data, tmp_path, capsys, monkeypatch):
    source, output, keys = data
    app.backup(source, output, keys)
    version = next((output / source.name / '1').glob('backup-*'))
    (keys / 'aes.key').unlink()
    target = tmp_path / 'restored'
    monkeypatch.setattr(app, 'require_root', lambda: None)
    assert app.main(['restore', '--output', str(output), '--project', source.name,
                     '--version', '1', '--keys', str(keys), '--target', str(target),
                     '--log', str(tmp_path / 'test.log')]) == 1
    message = capsys.readouterr().out
    assert 'Missing key' in message
    assert 'Traceback' not in message
    assert not target.exists()


def test_rotation(data):
    source, output, keys = data
    oldest = None
    for number in range(4):
        (source / 'file.txt').write_text(str(number))
        result = app.backup(source, output, keys, keep=3)
        if number == 0:
            oldest = output / source.name / '1'
    assert [path.name for path in app.version_folders(output / source.name)] == ['2', '3', '4']
    assert not oldest.exists()
    assert oldest.name in result


def test_no_changes(data):
    source, output, keys = data
    app.backup(source, output, keys)
    before = sorted(output.rglob('*'))
    assert 'SKIPPED_NO_CHANGES' in app.backup(source, output, keys)
    assert sorted(output.rglob('*')) == before


def test_signed_metadata(data):
    source, output, keys = data
    app.backup(source, output, keys)
    version = next((output / source.name / '1').glob('backup-*'))
    with (version / 'metadata.json').open('ab') as stream:
        stream.write(b' ')
    with pytest.raises(InvalidSignature):
        app.verify(version, keys)


def test_failed_selfcheck_preserves_versions(data, monkeypatch):
    source, output, keys = data
    app.backup(source, output, keys, keep=1)
    before = sorted(output.rglob('*'))
    (source / 'file.txt').write_text('new data')
    def fail(*args):
        raise ValueError('Simulated restore failure')
    monkeypatch.setattr(app, 'restore', fail)
    with pytest.raises(ValueError):
        app.backup(source, output, keys, keep=1)
    assert sorted(output.rglob('*')) == before


def test_restore_by_project_and_number(data, tmp_path, capsys, monkeypatch):
    source, output, keys = data
    app.backup(source, output, keys)
    (source / 'file.txt').write_text('Second version')
    app.backup(source, output, keys)
    target = tmp_path / 'restored'
    monkeypatch.setattr(app, 'require_root', lambda: None)
    assert app.main(['restore', '--output', str(output), '--project', source.name,
                     '--version', '1', '--keys', str(keys), '--target', str(target),
                     '--log', str(tmp_path / 'test.log')]) == 0
    assert (target / 'file.txt').read_text(encoding='utf-8') == 'Critical data'
    assert 'version 1' in capsys.readouterr().out


def test_independent_projects_and_custom_root(data, tmp_path):
    source, _, keys = data
    output = tmp_path / 'custom-backups'
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'notes.txt').write_text('Separate project')
    app.backup(other, output, keys, keep=3)
    app.backup(source, output, keys, keep=1)
    (source / 'file.txt').write_text('Change')
    app.backup(source, output, keys, keep=1)
    assert [path.name for path in app.version_folders(output / source.name)] == ['2']
    assert [path.name for path in app.version_folders(output / other.name)] == ['1']
    app.restore_project(output, 'other', 1, tmp_path / 'other-restored', keys)
    assert app.manifest(other) == app.manifest(tmp_path / 'other-restored')


def test_version_order_is_numeric(data):
    source, output, keys = data
    for number in range(11):
        (source / 'file.txt').write_text(str(number))
        app.backup(source, output, keys, keep=3)
    assert [path.name for path in app.version_folders(output / source.name)] == ['9', '10', '11']


def test_invalid_project_and_missing_version(data, tmp_path):
    source, output, keys = data
    app.backup(source, output, keys)
    with pytest.raises(ValueError, match='project name'):
        app.restore_project(output, '../source', 1, tmp_path / 'restored', keys)
    with pytest.raises(ValueError, match='was not found'):
        app.restore_project(output, source.name, 99, tmp_path / 'restored', keys)


def test_same_name_different_source_is_rejected(data, tmp_path):
    source, output, keys = data
    app.backup(source, output, keys)
    other = tmp_path / 'another-location' / source.name
    other.mkdir(parents=True)
    with pytest.raises(ValueError, match='different source'):
        app.backup(other, output, keys)


def test_linux_requires_root(monkeypatch):
    monkeypatch.setattr(app.sys, 'platform', 'linux')
    with pytest.raises(PermissionError, match='root'):
        app.require_root(euid=1000)


def test_log_records_command_and_is_private(tmp_path, monkeypatch):
    keys = tmp_path / 'keys'
    log = tmp_path / 'backup.log'
    monkeypatch.setattr(app, 'require_root', lambda: None)
    assert app.main(['init-keys', '--keys', str(keys), '--log', str(log)]) == 0
    content = log.read_text(encoding='utf-8')
    assert 'COMMAND_START command=init-keys' in content
    assert 'KEYS_CREATED' in content
    assert 'COMMAND_OK command=init-keys' in content
    if app.sys.platform.startswith('linux'):
        assert log.stat().st_mode & 0o777 == 0o600
