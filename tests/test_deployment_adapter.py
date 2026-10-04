"""Native adapter command protocol against synthetic metadata and actual temp Git."""
import json
import os
from pathlib import Path
import socket
import subprocess

import pytest

from scripts import inebotten_deploy as deploy
from utils.deployment_contract import DeploymentError, DeploymentManifest

IMAGE = 'sha256:' + '1'*64


def git(repo, *args):
    return subprocess.run(['git',*args],cwd=repo,check=True,capture_output=True,text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root=tmp_path/'repo';root.mkdir();git(root,'init','-b','master')
    git(root,'config','user.name','Fixture');git(root,'config','user.email','fixture@example.invalid')
    (root/'.gitignore').write_text('.env\ndata/\n.deployment/\n')
    (root/'Dockerfile').write_text('fixture source')
    asset=root/'features/data';asset.mkdir(parents=True);(asset/'school_calendars.json').write_text('{}')
    (root/'docker-compose.yml').write_text('fixture compose')
    git(root,'add','.');git(root,'add','-f','features/data/school_calendars.json');git(root,'-c','commit.gpgsign=false','commit','-m','fixture')
    (root/'.env').write_text('fixture secrets never in build');(root/'data').mkdir()
    return root


class InertDocker(deploy.DockerRuntime):
    def __init__(self, repo):
        super().__init__(repo)
        self.calls=[]
        self.labels={
            'org.opencontainers.image.revision':git(repo,'rev-parse','HEAD'),
            'io.inebotten.config-schema':'1', 'io.inebotten.data-schema-min':'0',
            'io.inebotten.data-schema-max':'1',
        }
        self.existing=False
        self.mount=str(repo/'data')
        self.archived_paths=None

    def command(self, *args, timeout=30):
        if args[0]=='git':return super().command(*args,timeout=timeout)
        self.calls.append(args)
        assert args[0]=='docker'
        if args[1:3]==('image','inspect'):
            return json.dumps(IMAGE) if args[4]=='{{json .Id}}' else json.dumps(self.labels)
        if args[1]=='ps':return 'fixture-container' if self.existing else ''
        if args[1]=='port':return f'127.0.0.1:{self.port}'
        if args[1]=='inspect':
            value=args[3]
            if 'working_dir' in value:return str(self.repo)
            if value=='{{json .Mounts}}':return json.dumps([{'Source':self.mount,'Destination':'/home/inebotten/.hermes','Type':'bind'}])
            if value=='{{.Image}}':return IMAGE
            raise AssertionError(args)
        if args[1]=='build':
            self.archived_paths={str(p.relative_to(args[-1])) for p in Path(args[-1]).rglob('*') if p.is_file()}
        return ''


def test_inspected_manifest_uses_image_id_and_full_image_labels(repo):
    runtime=InertDocker(repo)
    image=runtime.image('mutable-reference')
    assert image.image_digest==IMAGE
    assert image.revision==git(repo,'rev-parse','HEAD')
    runtime.labels['org.opencontainers.image.revision']='aaaaaaa'
    with pytest.raises(DeploymentError):runtime.image('mutable-reference')


def test_dirty_source_refuses_build_before_docker_call(repo):
    runtime=InertDocker(repo);(repo/'Dockerfile').write_text('WIP preserved')
    with pytest.raises(DeploymentError,match='dirty_source'):runtime.build()
    assert runtime.calls==[]
    assert (repo/'Dockerfile').read_text()=='WIP preserved'


def test_build_context_only_contains_committed_source_and_preserves_runtime_asset(repo):
    runtime=InertDocker(repo)
    image=runtime.build()
    assert image.revision==git(repo,'rev-parse','HEAD')
    assert 'features/data/school_calendars.json' in runtime.archived_paths
    assert '.env' not in runtime.archived_paths
    assert not any(path.startswith(('data/','.deployment/')) for path in runtime.archived_paths)
    assert (repo/'.env').read_text()=='fixture secrets never in build'
    assert not list(runtime.state.glob('build-*'))


def test_occupied_actual_loopback_port_is_refused(repo):
    runtime=InertDocker(repo)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));listener.listen()
        runtime.port=listener.getsockname()[1]
        assert runtime.port_available(None) is False
    assert runtime.port_available(None) is True


def test_wrong_existing_data_mount_never_stops_container(repo):
    runtime=InertDocker(repo);runtime.existing=True;runtime.mount=str(repo/'unrelated-data')
    with pytest.raises(DeploymentError,match='running_data_mount_mismatch'):runtime.stop()
    assert not any(call[1]=='stop' for call in runtime.calls)


def test_first_install_and_missing_rollback_evidence_use_actual_preflight(repo, monkeypatch):
    # Surrogate fixture UID exercises equality; no real UID 10001 or root operation.
    monkeypatch.setattr(deploy,'RUNTIME_UID',os.getuid())
    runtime=InertDocker(repo);runtime.port=0
    image=runtime.image('fixture')
    assert runtime.preflight(image,True) is None
    with pytest.raises(DeploymentError,match='missing_rollback_evidence'):runtime.preflight(image,False)
    mismatch=DeploymentManifest('b'*40,IMAGE,1,0,1)
    with pytest.raises(DeploymentError,match='candidate_source_mismatch'):runtime.preflight(mismatch,True)


def test_activate_retains_tag_and_only_replaces_owned_service_with_immutable_image(repo):
    runtime=InertDocker(repo);image=runtime.image('fixture')
    runtime.activate(image)
    assert ('docker','image','tag',IMAGE,'inebotten-candidate:'+'1'*64) in runtime.calls
    last=runtime.calls[-1]
    assert last[:2]==('docker','compose')
    assert last[-7:]==('up','-d','--no-build','--no-deps','--pull','never','inebotten')
    assert IMAGE in runtime.override.read_text()
    assert '!override' in runtime.override.read_text()
    assert not any('prune' in call or 'down' in call or '--remove-orphans' in call for call in runtime.calls)


def test_private_state_lock_and_cli_preflight_do_not_activate(repo, monkeypatch, capsys):
    runtime=InertDocker(repo);runtime.port=0
    monkeypatch.setattr(deploy,'RUNTIME_UID',os.getuid())
    monkeypatch.setattr(deploy,'DockerRuntime',lambda *a,**k:runtime)
    assert deploy.main(['--repo',str(repo),'--image',IMAGE,'--first-install'])==0
    assert 'preflight_passed' in capsys.readouterr().out
    assert runtime.state.stat().st_mode & 0o077==0
    assert not runtime.override.exists()
    assert not any('stop' in call or 'up' in call for call in runtime.calls)


def test_local_config_change_is_detected_without_returning_config_values(repo, monkeypatch):
    monkeypatch.setattr(deploy,'RUNTIME_UID',os.getuid())
    runtime=InertDocker(repo);runtime.port=0
    runtime.preflight(runtime.image('fixture'),True)
    (repo/'.env').write_text('changed fixture secret')
    with pytest.raises(DeploymentError,match='config_changed') as error:
        runtime.require_config_unchanged()
    assert 'secret' not in str(error.value)
