# Secure Backup Project

[Polska wersja](README_PL.md)

**Secure Backup Project** is a compact command-line tool for creating encrypted, automatically verified directory backups. It is developed as part of an **Operating Systems Security** university course and demonstrates practical data protection, access control, integrity verification, and safe restoration.

The target repository name is `Secure_Backup_Project`, while the application directory is named `Secure_Backup`. This is an academic demonstration project, not a production-ready backup system.

## Features

- full-backup encryption with AES-256-GCM,
- Ed25519 signatures covering metadata and the ciphertext digest,
- SHA-256 checksums of encrypted archives,
- automatic trial restoration of every new backup,
- manifest-based comparison of restored data with the source,
- change detection that avoids redundant versions,
- independent numbering and rotation for each project,
- restoration by project name and version number,
- protection against unsafe TAR paths and unsupported entries,
- a private text log describing application activity,
- restrictive Linux file and directory permissions,
- controlled user-facing errors without tracebacks.

## Target system and compatibility

The target environment is **Linux** with Python 3.12 or newer. On Linux, the application must run as root, applies `umask 077`, and validates key ownership and permissions.

The project should also run on modern Linux distributions such as Kali Linux, Debian, and Ubuntu when Python 3.12+ and `cryptography` are available.

The code and tests can run on Windows and macOS, but those systems do not provide the same security model:

- the root requirement is enforced only on Linux,
- Windows does not implement POSIX `chmod` permissions such as 0600 and 0700 in the same way,
- final ownership, symlink, and permission behavior must be verified on the target Linux system.

## How it works

When creating a backup, the program:

1. validates the source, key directory, output location, and retention limit;
2. builds a manifest containing relative paths and SHA-256 hashes of files;
3. rejects symbolic links and unsupported file types;
4. compares the manifest with the latest version and skips the operation when nothing changed;
5. creates a TAR archive in memory;
6. encrypts the TAR archive with AES-256-GCM and a fresh random nonce;
7. calculates SHA-256 over the ciphertext;
8. signs the metadata and ciphertext digest with Ed25519;
9. writes all artifacts to a private staging directory;
10. verifies the checksum and signature, decrypts the archive, safely extracts it, and compares the restored manifest with the source;
11. publishes the numbered version only after every check succeeds;
12. removes versions beyond the `--keep` limit and records the result in the log.

During restoration, SHA-256 and the Ed25519 signature are checked before decryption. The application then verifies the GCM authentication tag, validates every TAR entry, and compares the recovered files with the signed manifest.

## Backup format

Each source directory is treated as a separate project. Its project name is derived from the source directory name.

```text
backups/
└── small/
    ├── 1/
    │   └── backup-20261108T120000000000Z-a1b2c3/
    │       ├── archive.enc
    │       ├── archive.sha256
    │       ├── archive.sig
    │       └── metadata.json
    └── 2/
        └── backup-.../
```

| File | Purpose |
|---|---|
| `archive.enc` | Encrypted TAR archive. Its first 12 bytes contain the AES-GCM nonce. |
| `archive.sha256` | SHA-256 digest of the complete ciphertext. |
| `archive.sig` | Ed25519 signature over the metadata and ciphertext digest. |
| `metadata.json` | Plaintext but signed manifest, source path, project name, and version number. |

Metadata exposes file names and hashes. File contents are stored only inside the encrypted archive.

## Requirements

- Kali Linux, Debian, Ubuntu, or another modern Linux distribution,
- Python 3.12 or newer,
- `python3-venv`,
- `cryptography`,
- `pytest` for the test suite.

Python dependencies are listed in `requirements.txt`.

## Secure installation on Linux

Do not execute a virtual environment through `sudo` if an unprivileged user can modify it. The following example creates a root-owned deployment under `/opt` and root-owned application data under `/var/lib`:

```bash
cd Secure_Backup

sudo install -d -o root -g root -m 700 /opt/bso-secure-backup
sudo install -o root -g root -m 700 backup.py /opt/bso-secure-backup/backup.py
sudo install -o root -g root -m 600 requirements.txt /opt/bso-secure-backup/requirements.txt

sudo python3 -m venv /opt/bso-secure-backup/.venv
sudo /opt/bso-secure-backup/.venv/bin/pip install \
  -r /opt/bso-secure-backup/requirements.txt

sudo install -d -o root -g root -m 700 \
  /var/lib/bso-secure-backup/source \
  /var/log/bso-secure-backup

sudo cp -a test_data/small /var/lib/bso-secure-backup/source/small
sudo chown -R root:root /var/lib/bso-secure-backup
sudo chmod -R go-rwx /var/lib/bso-secure-backup
```

If virtual-environment support is missing:

```bash
sudo apt update
sudo apt install python3-venv
```

For development, tests may run in a normal user-owned local `.venv` without `sudo`. The root-owned `/opt` deployment is intended for running the application itself.

## Quick start

The following commands assume the deployment layout shown above.

### 1. Generate keys

```bash
sudo /opt/bso-secure-backup/.venv/bin/python \
  /opt/bso-secure-backup/backup.py init-keys \
  --keys /var/lib/bso-secure-backup/keys \
  --log /var/log/bso-secure-backup/backup.log
```

This creates:

- `aes.key` — a 256-bit AES key,
- `private.key` — an Ed25519 private key,
- `public.key` — an Ed25519 public key.

The key directory must be empty. Existing keys are never overwritten automatically.

### 2. Create a backup

```bash
sudo /opt/bso-secure-backup/.venv/bin/python \
  /opt/bso-secure-backup/backup.py backup \
  --source /var/lib/bso-secure-backup/source/small \
  --output /var/lib/bso-secure-backup/backups \
  --keys /var/lib/bso-secure-backup/keys \
  --keep 3 \
  --log /var/log/bso-secure-backup/backup.log
```

Example output:

```text
BACKUP_OK: small, version 1; restored and compared. Removed versions: []
```

Running the same command without modifying the source returns:

```text
SKIPPED_NO_CHANGES: no changes; no new version or rotation.
```

### 3. Restore a selected version

```bash
sudo /opt/bso-secure-backup/.venv/bin/python \
  /opt/bso-secure-backup/backup.py restore \
  --output /var/lib/bso-secure-backup/backups \
  --project small \
  --version 1 \
  --target /var/lib/bso-secure-backup/restored-v1 \
  --keys /var/lib/bso-secure-backup/keys \
  --log /var/log/bso-secure-backup/backup.log
```

The target must be absent or empty. Data is published there only after all verification steps pass.

## CLI commands and parameters

General help:

```bash
python backup.py --help
```

Command-specific help:

```bash
python backup.py init-keys --help
python backup.py backup --help
python backup.py restore --help
```

### `init-keys`

Creates a new key set without overwriting existing files.

| Parameter | Required | Description |
|---|:---:|---|
| `--keys PATH` | yes | Empty or absent directory in which the keys will be created. |
| `--log PATH` | no | Log file path. Defaults to `backup.log` in the current directory. |

### `backup`

Creates, verifies, and publishes a new version, or skips the operation when no data changed.

| Parameter | Required | Description |
|---|:---:|---|
| `--source PATH` | yes | Directory containing the data to protect. |
| `--output PATH` | yes | Root directory for all projects and versions. It must be outside the source and key directories. |
| `--keys PATH` | yes | Directory containing `aes.key`, `private.key`, and `public.key`. |
| `--keep N` | no | Number of newest valid versions to retain. Defaults to `3`; minimum is `1`. |
| `--log PATH` | no | Log file path. Defaults to `backup.log`. |

### `restore`

Restores a selected numbered version of a project.

| Parameter | Required | Description |
|---|:---:|---|
| `--output PATH` | yes | Backup archive root previously used by `backup`. |
| `--project NAME` | yes | Project name, which is the source directory name, for example `small`. |
| `--version N` | yes | Positive version number to restore. |
| `--target PATH` | yes | Absent or empty destination directory. |
| `--keys PATH` | yes | Directory containing the keys for this backup. |
| `--log PATH` | no | Log file path. Defaults to `backup.log`. |

## Main Python functions

The complete application is contained in `backup.py`.

| Function | Parameters | Responsibility |
|---|---|---|
| `manifest(folder)` | source directory | Returns paths, directories, and SHA-256 file hashes; rejects links and special files. |
| `init_keys(folder)` | key directory | Generates AES-256 and Ed25519 keys with private permissions. |
| `read_key(folder, name)` | key directory and file name | Validates existence, ownership, and permissions before reading a key. |
| `verify(version, keys)` | version and key directories | Verifies SHA-256 and the Ed25519 signature before decryption. |
| `backup(source, output, keys, keep=3)` | source, archive root, keys, limit | Performs creation, self-verification, publication, and rotation. |
| `restore(version, target, keys)` | artifact directory, destination, keys | Verifies, decrypts, safely extracts, and checks the manifest. |
| `restore_project(output, project, number, target, keys)` | archive root, project, number, destination, keys | Locates a numbered version and restores it. |
| `version_folders(project)` | project directory | Returns version directories in numeric order. |
| `configure_logger(path)` | log path | Opens a private text log and configures event recording. |
| `secure_tree(folder)` | data directory | Applies 0700 to directories and 0600 to files. |
| `require_root()` | none | Rejects non-root execution on Linux. |
| `main(argv=None)` | optional argument list | Builds the CLI and converts expected failures into concise messages. |

The functions can be imported by tests, but the CLI is the primary supported interface.

## Permissions and access control

On Linux, the application:

- requires effective UID 0,
- applies `umask 077` while running,
- creates private directories with mode 0700,
- creates keys, artifacts, logs, and restored files with mode 0600,
- checks the key directory and key-file owner and mode,
- rejects symbolic links used as key, backup, or log endpoints.

The program does not silently change source ownership or permissions. The administrator must protect source data explicitly.

```bash
sudo chown -R root:root /var/lib/bso-secure-backup/source
sudo chmod -R go-rwx /var/lib/bso-secure-backup/source
```

Inspect permissions with:

```bash
sudo stat -c '%U:%G %a %n' \
  /var/lib/bso-secure-backup/keys \
  /var/lib/bso-secure-backup/keys/* \
  /var/log/bso-secure-backup/backup.log

sudo find /var/lib/bso-secure-backup/backups -printf '%u:%g %m %p\n'
```

Running as root does not protect the application from a compromised root account. A larger system should use a dedicated service account with the minimum required privileges.

## Logging

Every command accepts an optional `--log` path. The log records:

- command start and result,
- verification and restoration stages,
- skipped unchanged backups,
- the newly created version,
- versions removed by rotation,
- the type and message of controlled failures.

The log does not contain key material or decrypted file contents. It is intended for demonstrations and diagnostics, not as a tamper-resistant audit trail.

```bash
sudo tail -n 30 /var/log/bso-secure-backup/backup.log
```

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Success, including an intentional no-change skip. |
| `1` | Controlled failure, such as a missing key, invalid signature, corrupted backup, or invalid path. |

## Tests

Development tests do not require root. Each test uses an isolated temporary directory.

```bash
cd Secure_Backup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -v
```

The test suite covers:

- successful backup and restoration,
- a single-bit ciphertext modification,
- a missing AES key,
- modified signed metadata,
- failed self-verification,
- unchanged data,
- version rotation,
- independent projects,
- restoration of an older version,
- version numbers greater than 9,
- invalid project and version selection,
- source-name conflicts,
- the Linux root requirement,
- basic log output and permissions.

Current local result:

```text
14 passed
```

Ownership, permission, and end-to-end behavior must still be verified on the target Kali Linux system.

## Large test-data generator

`generate_data.py` creates a deterministic set of 300-500 files with a total size of up to 200 MB.

```bash
python generate_data.py \
  --output test_data/generated \
  --count 300 \
  --mb 100 \
  --seed 2026
```

| Parameter | Default | Description |
|---|---:|---|
| `--output PATH` | none | Empty or absent destination directory. |
| `--count N` | `300` | Number of files in the range 300-500. |
| `--mb N` | `100` | Total size above 0 and no greater than 200 MB. |
| `--seed N` | `2026` | Random seed that makes generated content reproducible. |

Generated large data should not be committed to the repository.

## Repository structure

```text
Secure_Backup_Project/
└── Secure_Backup/
    ├── backup.py
    ├── generate_data.py
    ├── requirements.txt
    ├── pytest.ini
    ├── README.md
    ├── README_PL.md
    ├── tests/
    │   └── test_backup.py
    ├── test_data/small/
```

## Limitations

- The TAR archive and ciphertext are processed in memory.
- Backups, keys, and logs are local files; no off-site storage or HSM is provided.
- Concurrent backup creation and filesystem snapshots are not supported.
- Metadata is signed but not encrypted.
- The format is not compatible with the earlier modular project version.
- Security depends on the host, root account, keys, and complete Python environment.

## Intended audience

This project is intended for students, people learning Linux security, and instructors demonstrating backup protection concepts.

It can help explain:

- the difference between encryption, checksums, and digital signatures,
- key management and filesystem permissions,
- damage detection before decryption,
- safe archive extraction,
- automatic restore verification,
- version rotation and unchanged-data detection,
- the limitations of a simple local backup system.

The project can also serve as a foundation for labs, integrity-attack demonstrations, and experiments with keyrings, service accounts, external backup storage, or streaming encryption.
