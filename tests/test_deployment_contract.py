"""Disposable release rehearsal: no real Docker, providers, or personal stores."""
import json
from pathlib import Path

import pytest

from utils.deployment_contract import (
    DeploymentError, DeploymentManifest, preflight, store_schemas, verify_health,
)
from scripts.inebotten_deploy import deploy_candidate

OLD = 'a' * 40
NEW = 'b' * 40
OLD_IMAGE = 'sha256:' + '1' * 64
NEW_IMAGE = 'sha256:' + '2' * 64


def manifest(revision=NEW, image=NEW_IMAGE, maximum=1):
    return DeploymentManifest(revision, image, 1, 0, maximum)


def test_manifest_rejects_short_revision_mutable_image_and_invalid_ranges():
    for args in [('abcdef0', NEW_IMAGE, 1, 0, 1), (NEW, 'latest', 1, 0, 1),
                 (NEW, NEW_IMAGE, 1, 2, 1), (NEW, NEW_IMAGE, True, 0, 1)]:
        with pytest.raises(DeploymentError):
            DeploymentManifest(*args)


@pytest.mark.parametrize('dirty,free,port,rollback,code', [
    (True, 40, True, manifest(OLD, OLD_IMAGE), 'dirty_source'),
    (False, 1, True, manifest(OLD, OLD_IMAGE), 'insufficient_storage'),
    (False, 40, False, manifest(OLD, OLD_IMAGE), 'occupied_port'),
    (False, 40, True, None, 'missing_rollback_evidence'),
])
def test_preflight_blocks_before_any_activation(tmp_path, dirty, free, port, rollback, code):
    with pytest.raises(DeploymentError, match=code):
        preflight(manifest(), {}, dirty=dirty, free_bytes=free*1024**3,
                  port_available=port, rollback=rollback, first_install=False)


def test_older_code_refuses_newer_store_and_no_personal_data_is_changed(tmp_path):
    path = tmp_path / 'calendar.json'
    content = b'{"schema_version":2,"revision":3,"document":{"private":"fixture"}}'
    path.write_bytes(content)
    schemas = store_schemas(tmp_path)
    with pytest.raises(DeploymentError, match='incompatible_data'):
        manifest().require_compatible(schemas)
    assert path.read_bytes() == content
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize('status,revision', [('degraded', NEW), ('healthy', OLD), ('starting', NEW)])
def test_unhealthy_or_stale_health_never_passes(status, revision):
    with pytest.raises(DeploymentError):
        verify_health({'status': status, 'revision': revision, 'readiness': 'ready'}, manifest())


def test_required_subsystem_readiness_is_checked():
    with pytest.raises(DeploymentError):
        verify_health({'status':'healthy', 'revision':NEW, 'readiness':'degraded'}, manifest())


class FixtureRuntime:
    """Exercise the real transaction orchestration using an inert runtime adapter."""
    def __init__(self, root, *, bad_health=True, upgrade=False, failed_source=False):
        self.root = root
        self.current = manifest(OLD, OLD_IMAGE)
        self.events = []
        self.bad_health = bad_health
        self.upgrade = upgrade
        self.failed_source = failed_source
        self.config_changed = False

    def preflight(self, candidate, first_install):
        if self.failed_source:
            raise DeploymentError('source_sync_failed')
        preflight(candidate, store_schemas(self.root), dirty=False, free_bytes=40*1024**3,
                  port_available=True, rollback=self.current, first_install=first_install)
        return self.current

    def require_config_unchanged(self):
        if self.config_changed:raise DeploymentError("config_changed")

    def preserve(self, previous):
        self.events.append(('preserve', previous.image_digest))

    def activate(self, candidate):
        self.events.append(('activate', candidate.image_digest))
        self.current = candidate
        if self.upgrade and candidate.revision == NEW:
            (self.root / 'calendar.json').write_text(json.dumps({'schema_version':2,'revision':0,'document':{}}))

    def ready(self, candidate):
        verify_health({'status':'degraded' if self.bad_health and candidate.revision==NEW else 'healthy',
                       'revision':candidate.revision, 'readiness':'ready'}, candidate)

    def stop(self):
        self.events.append(('stop', self.current.image_digest))

    def schemas(self):
        return store_schemas(self.root)

    def record(self, status, candidate, previous):
        self.events.append(('record', status))


def test_failed_source_sync_never_stops_or_activates(tmp_path):
    runtime = FixtureRuntime(tmp_path, failed_source=True)
    with pytest.raises(DeploymentError, match='source_sync_failed'):
        deploy_candidate(runtime, manifest())
    assert runtime.events == []


def test_compatible_code_rollback_retains_store_bytes_and_both_images(tmp_path):
    path = tmp_path / 'calendar.json'
    content = b'{"schema_version":1,"revision":0,"document":{}}'
    path.write_bytes(content)
    runtime = FixtureRuntime(tmp_path)
    with pytest.raises(DeploymentError, match='candidate_failed_rolled_back'):
        deploy_candidate(runtime, manifest())
    assert runtime.current.image_digest == OLD_IMAGE
    assert runtime.events[:4] == [('preserve', OLD_IMAGE), ('record', 'prepared'), ('stop', OLD_IMAGE), ('activate', NEW_IMAGE)]
    assert ('activate', OLD_IMAGE) in runtime.events
    assert ('record', 'rolled_back') in runtime.events
    assert path.read_bytes() == content
    assert all(event[0] not in {'prune','restore_data'} for event in runtime.events)


def test_incompatible_data_holds_stopped_candidate_and_refuses_code_rollback(tmp_path):
    runtime = FixtureRuntime(tmp_path, upgrade=True)
    with pytest.raises(DeploymentError, match='rollback_blocked_data'):
        deploy_candidate(runtime, manifest(maximum=2))
    assert ('stop', NEW_IMAGE) in runtime.events
    assert ('activate', OLD_IMAGE) not in runtime.events
    assert ('record', 'rollback_blocked_data') in runtime.events
    assert store_schemas(tmp_path)['calendar.json'] == 2


def test_success_records_exact_image_and_does_not_rollback(tmp_path):
    runtime = FixtureRuntime(tmp_path, bad_health=False)
    assert deploy_candidate(runtime, manifest()) == manifest()
    assert runtime.events[-1] == ('record', 'healthy')
    assert [event for event in runtime.events if event[0]=='stop'] == [('stop', OLD_IMAGE)]


def test_store_probe_rejects_symlinks_and_corrupt_envelope(tmp_path):
    path = tmp_path / 'calendar.json'
    target = tmp_path / 'private.json'; target.write_text('{}')
    path.symlink_to(target)
    with pytest.raises(DeploymentError): store_schemas(tmp_path)
    path.unlink();path.write_text('{"schema_version":1,"document":[]}')
    with pytest.raises(DeploymentError): store_schemas(tmp_path)


def test_malformed_store_cannot_trigger_unsafe_rollback(tmp_path):
    class CorruptRuntime(FixtureRuntime):
        def activate(self, candidate):
            super().activate(candidate)
            if candidate.revision == NEW:
                (self.root/'calendar.json').write_text('{corrupt')
    runtime = CorruptRuntime(tmp_path)
    with pytest.raises(DeploymentError, match='rollback_blocked_data'):
        deploy_candidate(runtime, manifest())
    assert ('activate', OLD_IMAGE) not in runtime.events
    assert (tmp_path/'calendar.json').read_text() == '{corrupt'


def test_changed_config_blocks_reusing_previous_code_with_new_settings(tmp_path):
    class ChangedConfig(FixtureRuntime):
        def activate(self, candidate):
            super().activate(candidate)
            if candidate.revision == NEW:self.config_changed=True
    runtime=ChangedConfig(tmp_path)
    with pytest.raises(DeploymentError,match='rollback_blocked_config'):
        deploy_candidate(runtime,manifest())
    assert ('activate',OLD_IMAGE) not in runtime.events
    assert ('record','rollback_blocked_config') in runtime.events
