#!/usr/bin/env python3
"""Minimal encrypted backups using AES-GCM, Ed25519, and SHA-256."""

import argparse
import hashlib
import io
import json
import logging
import os
import shutil
import sys
import tarfile
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


LOGGER = logging.getLogger('bso-backup')


def require_root(euid=None):
    """Allow only root to run the application on the target Linux system."""
    if sys.platform.startswith('linux'):
        current_euid = os.geteuid() if euid is None else euid
        if current_euid != 0:
            raise PermissionError('On Linux, the program must be run as root.')


def configure_logger(path):
    """Create a private text log and return its handler for later cleanup."""
    if path.is_symlink():
        raise ValueError('The log file must not be a symbolic link.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.chmod(path, 0o600)
    stream = os.fdopen(descriptor, 'a', encoding='utf-8')
    handler = logging.StreamHandler(stream)
    formatter = logging.Formatter('%(asctime)sZ %(levelname)s %(message)s',
                                  datefmt='%Y-%m-%dT%H:%M:%S')
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    return handler


def secure_tree(folder):
    """Restrict restored data to its owner: directories 0700, files 0600."""
    folder.chmod(0o700)
    for path in folder.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'Symbolic links are not supported: {path}')
        path.chmod(0o700 if path.is_dir() else 0o600)


def check_private_path(path, directory=False):
    """On Linux, reject objects accessible to the group or other users."""
    if not sys.platform.startswith('linux'):
        return
    status = path.stat()
    if status.st_uid != os.geteuid():
        raise PermissionError(f'Invalid owner of protected path: {path}')
    if status.st_mode & 0o077:
        kind = 'Directory' if directory else 'File'
        raise PermissionError(f'{kind} must be accessible only to its owner: {path}')


def json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')


def manifest(folder):
    """Return paths, directories, and file hashes; reject symbolic links."""
    result = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symbolic links are not supported: {path}')
        if path.is_dir():
            result[path.relative_to(folder).as_posix()] = None
        elif path.is_file():
            with path.open('rb') as stream:
                result[path.relative_to(folder).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
        else:
            raise ValueError(f'Unsupported file type: {path}')
    return result


def init_keys(folder):
    if folder.is_symlink():
        raise ValueError('The key directory must not be a symbolic link.')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(folder.iterdir()):
        raise ValueError('The key directory must be empty; existing keys will not be overwritten.')
    folder.chmod(0o700)
    private = Ed25519PrivateKey.generate()
    values = {
        'aes.key': AESGCM.generate_key(bit_length=256),
        'private.key': private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                             serialization.NoEncryption()),
        'public.key': private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
    }
    for name, value in values.items():
        with (folder / name).open('xb') as stream:
            os.chmod(folder / name, 0o600)
            stream.write(value)
    LOGGER.info('KEYS_CREATED directory=%s files=%s', folder, ','.join(values))
    return 'KEYS_OK: keys created.'


def read_key(folder, name):
    check_private_path(folder, directory=True)
    path = folder / name
    if not path.is_file():
        raise ValueError(f'Missing key: {path}')
    check_private_path(path)
    return path.read_bytes()


def verify(version, keys):
    """Verify the checksum and signature before decryption."""
    LOGGER.info('VERIFY_START version=%s', version)
    check_private_path(version, directory=True)
    for name in ('archive.enc', 'archive.sha256', 'archive.sig', 'metadata.json'):
        check_private_path(version / name)
    encrypted = (version / 'archive.enc').read_bytes()
    digest = hashlib.sha256(encrypted).hexdigest()
    if digest != (version / 'archive.sha256').read_text().strip():
        raise ValueError('Corrupted backup: SHA-256 mismatch detected before restoration.')
    metadata_bytes = (version / 'metadata.json').read_bytes()
    public = Ed25519PublicKey.from_public_bytes(read_key(keys, 'public.key'))
    public.verify((version / 'archive.sig').read_bytes(), metadata_bytes + b'\n' + digest.encode())
    LOGGER.info('VERIFY_OK version=%s sha256=%s', version, digest)
    return encrypted, json.loads(metadata_bytes)


def version_folders(project):
    return sorted((path for path in project.iterdir()
                   if path.is_dir() and not path.is_symlink() and path.name.isascii()
                   and path.name.isdigit() and int(path.name) > 0), key=lambda path: int(path.name))


def restore_project(output, project, number, target, keys):
    if not project or project in ('.', '..') or '/' in project or '\\' in project or number < 1:
        raise ValueError('Provide a project name and a positive version number.')
    root = output.resolve()
    folder = (root / project / str(number)).resolve()
    if not folder.is_relative_to(root) or not folder.is_dir():
        raise ValueError(f'Project {project}, version {number} was not found.')
    archives = list(folder.glob('backup-*'))
    if len(archives) != 1 or not archives[0].is_dir() or archives[0].is_symlink():
        raise ValueError('A version must contain exactly one backup directory.')
    message = restore(archives[0], target, keys)
    return f'{project}, version {number}: {message}'


def restore(version, target, keys):
    LOGGER.info('RESTORE_START version=%s target=%s', version, target)
    encrypted, metadata = verify(version, keys)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError('The restore directory must be empty.')
    archive_bytes = AESGCM(read_key(keys, 'aes.key')).decrypt(encrypted[:12], encrypted[12:], json_bytes(metadata))
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        restored = Path(temporary) / 'data'
        restored.mkdir(mode=0o700)
        with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                    raise ValueError('Unsafe archive entry.')
                if not (restored / member.name).resolve().is_relative_to(restored.resolve()):
                    raise ValueError('Path escapes the restore directory.')
            archive.extractall(restored, filter='data')
        secure_tree(restored)
        if manifest(restored) != metadata['files']:
            raise ValueError('Restored files do not match the manifest.')
        if target.exists():
            target.rmdir()
        restored.rename(target)
    LOGGER.info('RESTORE_OK version=%s target=%s', version, target)
    return 'RESTORE_OK: data restored; files match the manifest.'


def backup(source, output, keys, keep=3):
    if output.is_symlink() or keys.is_symlink():
        raise ValueError('Neither the backup nor key directory may be a symbolic link.')
    source, output, keys = source.resolve(), output.resolve(), keys.resolve()
    if not source.is_dir() or keep < 1:
        raise ValueError('The source must be a directory and the version limit must be at least 1.')
    if output.is_relative_to(source) or keys.is_relative_to(source):
        raise ValueError('Backups and keys must be stored outside the source directory.')
    if output.is_relative_to(keys) or keys.is_relative_to(output):
        raise ValueError('Keys and backups must be stored in separate directories.')
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    project = output / source.name
    if not source.name or project.is_symlink():
        raise ValueError('Invalid project directory.')
    project.mkdir(exist_ok=True, mode=0o700)
    project.chmod(0o700)
    LOGGER.info('BACKUP_START source=%s project=%s keep=%s', source, project, keep)
    versions = version_folders(project)
    files = manifest(source)
    if versions:
        archives = list(versions[-1].glob('backup-*'))
        if len(archives) != 1:
            raise ValueError('Invalid latest-version directory.')
        _, previous = verify(archives[0], keys)
        if previous['source'] != str(source):
            raise ValueError('This backup directory is assigned to a different source.')
        if previous['files'] == files:
            LOGGER.info('BACKUP_SKIPPED_NO_CHANGES source=%s project=%s', source, project)
            return 'SKIPPED_NO_CHANGES: no changes; no new version or rotation.'
    number = int(versions[-1].name) + 1 if versions else 1
    metadata = {'source': str(source), 'files': files, 'project': source.name, 'version': number}
    key = read_key(keys, 'aes.key')
    private = Ed25519PrivateKey.from_private_bytes(read_key(keys, 'private.key'))
    with io.BytesIO() as buffer:
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            for name in files:
                archive.add(source / name, arcname=name, recursive=False)
        nonce = os.urandom(12)
        encrypted = nonce + AESGCM(key).encrypt(nonce, buffer.getvalue(), json_bytes(metadata))
    if manifest(source) != files:
        raise ValueError('The source changed while the backup was being created.')
    digest = hashlib.sha256(encrypted).hexdigest()
    archive_name = 'backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + os.urandom(3).hex()
    # Assign the final version name only after the staged backup passes verification.
    with tempfile.TemporaryDirectory(prefix='.pending-', dir=project) as temporary:
        pending_version = Path(temporary) / str(number)
        staging = pending_version / archive_name
        staging.mkdir(parents=True, mode=0o700)
        artifacts = {'archive.enc': encrypted, 'metadata.json': json_bytes(metadata),
                     'archive.sha256': digest.encode(),
                     'archive.sig': private.sign(json_bytes(metadata) + b'\n' + digest.encode())}
        for name, value in artifacts.items():
            with (staging / name).open('xb') as stream:
                os.chmod(staging / name, 0o600)
                stream.write(value)
        restored = Path(temporary) / 'restored'
        restore(staging, restored, keys)
        if manifest(restored) != manifest(source):
            raise ValueError('The verification restore differs from the original source.')
        pending_version.rename(project / str(number))
        (project / str(number)).chmod(0o700)
    removed = []
    for old in version_folders(project)[:-keep]:
        shutil.rmtree(old)
        removed.append(old.name)
    LOGGER.info('BACKUP_OK source=%s project=%s version=%s removed=%s',
                source, project, number, ','.join(removed) if removed else '-')
    return f'BACKUP_OK: {source.name}, version {number}; restored and compared. Removed versions: {removed}'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init-keys')
    init.add_argument('--keys', type=Path, required=True)
    init.add_argument('--log', type=Path, default=Path('backup.log'))
    create = commands.add_parser('backup')
    create.add_argument('--source', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--keys', type=Path, required=True)
    create.add_argument('--keep', type=int, default=3)
    create.add_argument('--log', type=Path, default=Path('backup.log'))
    recover = commands.add_parser('restore')
    recover.add_argument('--output', type=Path, required=True, help='backup archive root')
    recover.add_argument('--project', required=True, help='source directory name')
    recover.add_argument('--version', type=int, required=True, help='version number, for example 1')
    recover.add_argument('--target', type=Path, required=True)
    recover.add_argument('--keys', type=Path, required=True)
    recover.add_argument('--log', type=Path, default=Path('backup.log'))
    args = parser.parse_args(argv)
    handler = None
    previous_umask = None
    try:
        require_root()
        previous_umask = os.umask(0o077)
        handler = configure_logger(args.log)
        LOGGER.info('COMMAND_START command=%s uid=%s', args.command,
                    os.geteuid() if hasattr(os, 'geteuid') else 'windows')
        if args.command == 'init-keys':
            message = init_keys(args.keys)
        elif args.command == 'backup':
            message = backup(args.source, args.output, args.keys, args.keep)
        else:
            message = restore_project(args.output, args.project, args.version, args.target, args.keys)
        LOGGER.info('COMMAND_OK command=%s', args.command)
        print(message)
        return 0
    except (InvalidSignature, InvalidTag):
        LOGGER.error('COMMAND_FAILED command=%s reason=integrity_or_key', args.command)
        print('ERROR: invalid signature, ciphertext, or key.')
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as error:
        LOGGER.error('COMMAND_FAILED command=%s error=%s message=%s',
                     args.command, type(error).__name__, error)
        print(f'ERROR: {error}')
    finally:
        if handler is not None:
            handler.flush()
            handler.stream.close()
            handler.close()
            LOGGER.removeHandler(handler)
        if previous_umask is not None:
            os.umask(previous_umask)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
