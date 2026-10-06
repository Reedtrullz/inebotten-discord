#!/usr/bin/env python3
"""Read-only deployment preflight by default; --apply explicitly activates code.

The operator must have already reviewed config, migration and live backup gates.
Only the inebotten service is replaced. Retained images and data are never pruned.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time

RUNTIME_UID = 10001
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.deployment_contract import (
    DeploymentError,
    DeploymentManifest, preflight, store_schemas, verify_health,
)
from utils.backup_bundle import _directory, _read_regular, BackupError
from utils.store_ownership import ProcessOwnership, StoreOwnedError
from scripts.deployment_health import local_opener


def deploy_candidate(runtime, candidate, *, first_install=False):
    previous = runtime.preflight(candidate, first_install)
    if previous is not None:
        runtime.preserve(previous)
    runtime.record('prepared', candidate, previous)
    if previous is not None:
        runtime.stop()
        try:
            schemas = runtime.schemas()
            candidate.require_compatible(schemas)
            previous.require_compatible(schemas)
        except DeploymentError:
            runtime.record('activation_blocked_data', candidate, previous)
            raise DeploymentError('activation_blocked_data') from None
    try:
        runtime.require_config_unchanged()
    except DeploymentError:
        runtime.record('activation_blocked_config', candidate, previous)
        raise DeploymentError('activation_blocked_config') from None
    try:
        runtime.activate(candidate)
        runtime.ready(candidate)
        runtime.require_config_unchanged()
    except (DeploymentError, OSError, subprocess.SubprocessError):
        runtime.stop()  # quiesce the candidate before reading compatibility headers
        if previous is None:
            runtime.record('failed_first_install', candidate, None)
            raise DeploymentError('candidate_failed_no_previous_code') from None
        try:
            previous.require_compatible(runtime.schemas())
        except DeploymentError:
            runtime.record('rollback_blocked_data', candidate, previous)
            raise DeploymentError('rollback_blocked_data') from None
        try:
            runtime.require_config_unchanged()
        except DeploymentError:
            runtime.record('rollback_blocked_config', candidate, previous)
            raise DeploymentError('rollback_blocked_config') from None
        try:
            runtime.activate(previous)
            runtime.ready(previous)
        except (DeploymentError, OSError, subprocess.SubprocessError):
            runtime.stop()
            runtime.record('rollback_failed', candidate, previous)
            raise DeploymentError('rollback_failed') from None
        runtime.record('rolled_back', candidate, previous)
        raise DeploymentError('candidate_failed_rolled_back') from None
    runtime.record('healthy', candidate, previous)
    return candidate


class DockerRuntime:
    def __init__(self, repo, profile='compose', *, deadline=120):
        self.repo = Path(repo).resolve()
        self.profile = profile
        self.port = 8081 if profile == 'compose-host-caddy' else 8080
        self.state = _directory(self.repo / '.deployment')
        self.deadline = deadline
        self._probe_deadline = None
        self.container = 'inebotten-bot'
        self.override = self.state / 'active-compose.yml'

    def command(self, *arguments, timeout=30):
        if self._probe_deadline is not None:
            remaining = self._probe_deadline - time.monotonic()
            if remaining <= 0:
                raise DeploymentError("readiness_deadline")
            timeout = min(timeout, remaining)
        try:
            result = subprocess.run(list(arguments), cwd=self.repo, capture_output=True,
                                    text=True, timeout=timeout, check=True)
        except (OSError, subprocess.SubprocessError):
            raise DeploymentError('command_failed_' + arguments[0]) from None
        if len(result.stdout.encode()) > 2*1024**2:
            raise DeploymentError('command_output_too_large')
        return result.stdout.strip()

    def image(self, reference):
        # Format reads immutable metadata only; never dump the image configuration.
        metadata = json.loads(self.command('docker', 'image', 'inspect', '--format',
                             '{{json .Id}}', reference))
        labels = json.loads(self.command('docker', 'image', 'inspect', '--format', '{{json .Config.Labels}}', reference)) or {}
        try:
            return DeploymentManifest(labels['org.opencontainers.image.revision'], metadata,
                                      int(labels['io.inebotten.config-schema']),
                                      int(labels['io.inebotten.data-schema-min']),
                                      int(labels['io.inebotten.data-schema-max']))
        except (KeyError, TypeError, ValueError):
            raise DeploymentError('missing_or_invalid_image_contract') from None

    def running(self):
        found = self.command('docker', 'ps', '-a', '--filter', 'name=^/inebotten-bot$', '--format', '{{.ID}}')
        if not found:
            return None
        working_dir = self.command('docker', 'inspect', '--format',
                                  '{{index .Config.Labels "com.docker.compose.project.working_dir"}}', self.container)
        if working_dir != str(self.repo):
            raise DeploymentError('container_not_owned_by_this_checkout')
        mounts = json.loads(self.command('docker', 'inspect', '--format', '{{json .Mounts}}', self.container))
        if not any(mount.get('Source') == str(self.repo/'data')
                   and mount.get('Destination') == '/home/inebotten/.hermes'
                   and mount.get('Type') == 'bind' for mount in mounts):
            raise DeploymentError('running_data_mount_mismatch')
        return self.image(self.command('docker', 'inspect', '--format', '{{.Image}}', self.container))

    def schemas(self):
        return store_schemas(self.repo / 'data' / 'discord' / 'data')

    def port_available(self, previous):
        if previous is not None:
            mapping = self.command('docker', 'port', self.container, '8080/tcp')
            if mapping == f'127.0.0.1:{self.port}':
                return True
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', self.port))
                return True
            except OSError:
                return False

    def source_revision(self):
        if self.command('git', 'status', '--porcelain', '--untracked-files=normal'):
            raise DeploymentError('dirty_source')
        return self.command('git', 'rev-parse', 'HEAD')

    def preflight(self, candidate, first_install):
        revision = self.source_revision()
        if candidate.revision != revision:
            raise DeploymentError('candidate_source_mismatch')
        # Configuration bytes are hashed locally, never echoed or placed in receipts.
        try:
            env_file = self.repo / '.env'
            if env_file.is_symlink() or not env_file.is_file():
                raise DeploymentError('missing_or_unsafe_config')
            data = _directory(self.repo / 'data')
            if not data.is_dir() or data.stat().st_uid != RUNTIME_UID:
                raise DeploymentError('data_directory_requires_reviewed_uid_10001')
        except (BackupError, OSError):
            raise DeploymentError('unsafe_data_directory') from None
        self._config_digest = self.config_digest()
        previous = self.running()
        preflight(candidate, self.schemas(), dirty=False, free_bytes=shutil.disk_usage(self.repo).free,
                  port_available=self.port_available(previous), rollback=previous, first_install=first_install)
        return previous

    def config_digest(self):
        try:
            return hashlib.sha256(_read_regular(self.repo/'.env', 64*1024)).digest()
        except BackupError:
            raise DeploymentError('unsafe_config') from None

    def require_config_unchanged(self):
        if self.config_digest() != self._config_digest:
            raise DeploymentError('config_changed')

    def write_metadata(self, name, content):
        self.state.mkdir(mode=0o700, exist_ok=True)
        if self.state.stat().st_mode & 0o077:
            raise DeploymentError('deployment_directory_must_be_private')
        path = self.state / name
        if path.is_symlink():
            raise DeploymentError('unsafe_deployment_metadata')
        with tempfile.NamedTemporaryFile(mode='w', dir=self.state, delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(content); handle.flush(); os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)

    def preserve(self, previous):
        tag = 'inebotten-rollback:' + previous.image_digest.split(':')[1]
        self.command('docker', 'image', 'tag', previous.image_digest, tag)
        self.write_metadata('rollback-' + previous.image_digest.split(':')[1] + '.json',
                            json.dumps(previous.document(), indent=2) + '\n')

    def record(self, status, candidate, previous):
        self.write_metadata('deployment.json', json.dumps({
            'status': status, 'profile': self.profile,
            'candidate': candidate.document(), 'previous': previous.document() if previous else None,
            'data_restore_performed': False,
        }, indent=2) + '\n')

    def compose(self, *arguments):
        return self.command('docker', 'compose', '-f', str(self.repo/'docker-compose.yml'),
                            '-f', str(self.override), *arguments, timeout=180)

    def activate(self, candidate):
        # An explicit -f pair avoids accidentally loading an unrelated override.
        self.command('docker', 'image', 'tag', candidate.image_digest,
                     'inebotten-candidate:' + candidate.image_digest.split(':')[1])
        self.write_metadata('active-compose.yml', 'services:\n  inebotten:\n'
                            f'    image: {candidate.image_digest}\n'
                            '    ports: !override\n'
                            f'      - "127.0.0.1:{self.port}:8080"\n')
        self.compose('up', '-d', '--no-build', '--no-deps', '--pull', 'never', 'inebotten')

    def stop(self):
        # Refuse to stop an unrelated named container, including one created concurrently.
        if self.running() is None:
            return
        self.command('docker', 'stop', '--time', '20', self.container, timeout=35)

    def ready(self, candidate):
        deadline = time.monotonic() + self.deadline
        self._probe_deadline = deadline
        opener = local_opener()
        try:
            while time.monotonic() < deadline:
                try:
                    actual = self.running()
                    if actual != candidate:
                        raise DeploymentError('unexpected_running_image')
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    with opener.open(f'http://127.0.0.1:{self.port}/health', timeout=min(3, remaining)) as response:
                        raw = response.read(32769)
                        if len(raw) > 32768:
                            raise DeploymentError('health_response_too_large')
                        verify_health(json.loads(raw), candidate)
                    return
                except (OSError, ValueError, DeploymentError):
                    time.sleep(min(1, max(0, deadline-time.monotonic())))
            raise DeploymentError('readiness_deadline')
        finally:
            self._probe_deadline = None

    def build(self):
        revision = self.source_revision()
        if shutil.disk_usage(self.repo).free < 30*1024**3:
            raise DeploymentError('insufficient_storage')
        self.state.mkdir(mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='build-', dir=self.state) as directory:
            # git archive excludes ignored configs/data/venvs. Limit context to 64 MiB.
            raw = subprocess.run(['git','archive','--format=tar',revision], cwd=self.repo,
                                 capture_output=True, timeout=30, check=True).stdout
            if len(raw) > 64*1024**2:
                raise DeploymentError('source_archive_too_large')
            with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
                if any(member.issym() or member.islnk() for member in archive.getmembers()):
                    raise DeploymentError('source_archive_symlink')
                archive.extractall(directory, filter='data')
            tag = 'inebotten-candidate:' + revision
            self.command('docker', 'build', '--build-arg', 'SOURCE_COMMIT='+revision,
                         '--tag', tag, directory, timeout=1200)
            return self.image(tag)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--profile', choices=('compose', 'compose-host-caddy'), default='compose')
    parser.add_argument('--image', help='prebuilt image ID; inspected against full source revision')
    parser.add_argument('--build', action='store_true', help='build only committed source in a bounded context')
    parser.add_argument('--first-install', action='store_true', help='no previous container and no owned stores')
    parser.add_argument('--apply', action='store_true', help='explicitly replace this service, with compatible code rollback')
    args = parser.parse_args(argv)
    ownership = None
    try:
        runtime = DockerRuntime(args.repo, args.profile)
        if args.build and args.image:
            raise DeploymentError('select_image_or_build')
        if not args.build and not args.image:
            raise DeploymentError('candidate_image_required')
        # Serialize source preflight/build/activation against cooperating operators.
        runtime.state.mkdir(mode=0o700, exist_ok=True)
        if runtime.state.stat().st_mode & 0o077:
            raise DeploymentError('deployment_directory_must_be_private')
        ownership = ProcessOwnership(runtime.state/'operator')
        ownership.acquire()
        candidate = runtime.build() if args.build else runtime.image(args.image)
        if args.apply:
            deploy_candidate(runtime, candidate, first_install=args.first_install)
            print(json.dumps({'status':'healthy', **candidate.document()}))
        else:
            runtime.preflight(candidate, args.first_install)
            print(json.dumps({'status':'preflight_passed', **candidate.document()}))
        return 0
    except (DeploymentError, BackupError, StoreOwnedError, OSError, ValueError, subprocess.SubprocessError) as error:
        # Non-contract errors are intentionally content-free.
        print(str(error) if isinstance(error, DeploymentError) else 'deployment_check_failed', file=sys.stderr)
        return 1
    finally:
        if ownership is not None:
            ownership.close()


if __name__ == '__main__':
    raise SystemExit(main())
