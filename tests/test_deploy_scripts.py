"""Real disposable Git repositories exercise the installed updater shell path."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.run(['git',*args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def fixture(tmp_path):
    origin = tmp_path/'origin'; origin.mkdir();git(origin,'init','--bare')
    repo=tmp_path/'repo';repo.mkdir();git(repo,'init','-b','master')
    git(repo,'config','user.name','Fixture');git(repo,'config','user.email','fixture@example.invalid')
    (repo/'.gitignore').write_text('.env\ndata/\n')
    (repo/'scripts').mkdir()
    (repo/'scripts/inebotten_deploy.py').write_text(
        "import os,sys,json\nfrom pathlib import Path\n"
        "Path(os.environ['FIXTURE_RECEIPT']).write_text(json.dumps(sys.argv[1:]))\n"
        "raise SystemExit(int(os.environ.get('FIXTURE_DEPLOY_EXIT','0')))\n")
    git(repo,'add','.');git(repo,'-c','commit.gpgsign=false','commit','-m','fixture')
    git(repo,'remote','add','origin',str(origin));git(repo,'push','-u','origin','master')
    (repo/'.env').write_text('fixture config preserved')
    (repo/'data').mkdir();(repo/'data/calendar.json').write_text('fixture private bytes')
    bin_dir=tmp_path/'bin';bin_dir.mkdir()
    (bin_dir/'flock').write_text('#!/bin/sh\nexit 0\n');(bin_dir/'flock').chmod(0o755)
    return repo, origin, bin_dir


def run_update(tmp_path, repo, bin_dir, **extra):
    env={**os.environ, 'PATH':str(bin_dir)+os.pathsep+os.environ['PATH'],
         'INEBOTTEN_REPO':str(repo), 'INEBOTTEN_UPDATE_LOG':str(tmp_path/'update.log'),
         'INEBOTTEN_UPDATE_LOCK':str(tmp_path/'update.lock'),
         'INEBOTTEN_PYTHON':__import__('sys').executable,
         'FIXTURE_RECEIPT':str(tmp_path/'called.json'), **extra}
    return subprocess.run(['bash',str(ROOT/'scripts/deploy/inebotten-update')], env=env,
                          capture_output=True, timeout=20)


def test_update_calls_shared_contract_and_only_claims_verified_success(tmp_path):
    repo,origin,bin_dir=fixture(tmp_path)
    result=run_update(tmp_path,repo,bin_dir)
    assert result.returncode==0
    assert '--build' in (tmp_path/'called.json').read_text()
    assert '--apply' in (tmp_path/'called.json').read_text()
    assert git(repo,'rev-parse','HEAD') in (tmp_path/'update.log').read_text()
    assert (repo/'.env').read_text()=='fixture config preserved'
    assert (repo/'data/calendar.json').read_text()=='fixture private bytes'


def test_dirty_checkout_is_preserved_without_service_action(tmp_path):
    repo,origin,bin_dir=fixture(tmp_path)
    file=repo/'scripts/inebotten_deploy.py';file.write_text('preserved WIP')
    assert run_update(tmp_path,repo,bin_dir).returncode!=0
    assert file.read_text()=='preserved WIP'
    assert not (tmp_path/'called.json').exists()


def test_failed_source_fetch_never_calls_deployer(tmp_path):
    repo,origin,bin_dir=fixture(tmp_path)
    git(repo,'remote','set-url','origin',str(tmp_path/'not-a-repository'))
    before=git(repo,'rev-parse','HEAD')
    assert run_update(tmp_path,repo,bin_dir).returncode!=0
    assert git(repo,'rev-parse','HEAD')==before
    assert not (tmp_path/'called.json').exists()


def test_failed_candidate_health_is_not_reported_as_update_success(tmp_path):
    repo,origin,bin_dir=fixture(tmp_path)
    assert run_update(tmp_path,repo,bin_dir,FIXTURE_DEPLOY_EXIT='1').returncode==1
    assert 'Verified deployment' not in (tmp_path/'update.log').read_text()


def test_non_fast_forward_source_is_refused_without_losing_local_commit(tmp_path):
    repo,origin,bin_dir=fixture(tmp_path)
    other=tmp_path/'other';git(tmp_path,'clone',str(origin),str(other))
    git(other,'config','user.name','Fixture');git(other,'config','user.email','fixture@example.invalid')
    (other/'remote.txt').write_text('remote');git(other,'add','.');git(other,'-c','commit.gpgsign=false','commit','-m','remote');git(other,'push')
    (repo/'local.txt').write_text('local');git(repo,'add','.');git(repo,'-c','commit.gpgsign=false','commit','-m','local')
    before=git(repo,'rev-parse','HEAD')
    assert run_update(tmp_path,repo,bin_dir).returncode!=0
    assert git(repo,'rev-parse','HEAD')==before
    assert not (tmp_path/'called.json').exists()


def test_install_autoupdate_preserves_existing_secret_and_restarts_services():
    content=(ROOT/'scripts/deploy/install-autoupdate.sh').read_text()
    assert 'existing_env_value WEBHOOK_SECRET' in content
    assert 'systemctl restart inebotten-webhook.service' in content
    assert 'systemctl restart inebotten-update.timer' in content
