"""Content-free deployment metadata and bounded compatibility checks.

A Docker image ID is a local content digest, not a registry distribution digest.
Code rollback never restores, migrates, or rewrites a data store.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re

from utils.backup_bundle import STORE_SCHEMAS, MAX_STORE_BYTES, _directory, _read_regular, BackupError

CONFIG_SCHEMA = 1
DATA_SCHEMA_MIN = 0  # readable legacy documents
DATA_SCHEMA_MAX = 1
MIN_FREE_BYTES = 30 * 1024**3


class DeploymentError(RuntimeError):
    """Stable codes only: never include config values, private documents or CLI output."""


@dataclass(frozen=True)
class DeploymentManifest:
    revision: str
    image_digest: str
    config_schema: int
    data_schema_min: int
    data_schema_max: int

    def __post_init__(self):
        if (not isinstance(self.revision, str) or not re.fullmatch('[0-9a-f]{40}', self.revision)
                or not isinstance(self.image_digest, str)
                or not re.fullmatch('sha256:[0-9a-f]{64}', self.image_digest)
                or any(type(n) is not int for n in (self.config_schema, self.data_schema_min, self.data_schema_max))
                or self.config_schema != CONFIG_SCHEMA
                or not 0 <= self.data_schema_min <= self.data_schema_max <= 100):
            raise DeploymentError('invalid_manifest')

    def require_compatible(self, schemas):
        if any(not self.data_schema_min <= version <= self.data_schema_max for version in schemas.values()):
            raise DeploymentError('incompatible_data')

    def document(self):
        return {'manifest_version': 1, 'image_digest_kind': 'docker_image_id', **asdict(self)}


def built_revision(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    try:
        value = (root / 'commit_hash.txt').read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        return None
    return value if re.fullmatch('[0-9a-f]{40}', value) else None


def store_schemas(root):
    """Inspect only five owned stores; no discovery, initialization, or sensitive output."""
    try:
        root = _directory(root)
        schemas = {}
        for name in STORE_SCHEMAS:
            path = root / name
            if not path.exists() and not path.is_symlink():
                continue
            value = json.loads(_read_regular(path, MAX_STORE_BYTES))
            if not isinstance(value, dict):
                raise DeploymentError('invalid_store')
            version = value.get('schema_version', 0)
            if type(version) is not int or version < 0:
                raise DeploymentError('invalid_store')
            if 'schema_version' in value and (not isinstance(value.get('document'), dict)
                    or type(value.get('revision', 0)) is not int or value.get('revision', 0) < 0):
                raise DeploymentError('invalid_store')
            schemas[name] = version
        return schemas
    except (BackupError, OSError, ValueError, UnicodeError) as error:
        raise DeploymentError('unsafe_or_invalid_store') from error


def preflight(candidate, schemas, *, dirty, free_bytes, port_available, rollback, first_install):
    if dirty:
        raise DeploymentError('dirty_source')
    if free_bytes < MIN_FREE_BYTES:
        raise DeploymentError('insufficient_storage')
    if not port_available:
        raise DeploymentError('occupied_port')
    candidate.require_compatible(schemas)
    if rollback is None:
        if not first_install:
            raise DeploymentError('missing_rollback_evidence')
        if schemas:
            raise DeploymentError('first_install_requires_empty_owned_stores')
    else:
        if first_install:
            raise DeploymentError('first_install_has_existing_container')
        rollback.require_compatible(schemas)


def verify_health(health, manifest):
    if (not isinstance(health, dict) or health.get('status') != 'healthy'
            or health.get('revision') != manifest.revision or health.get('readiness') != 'ready'):
        raise DeploymentError('unhealthy_or_stale_revision')
