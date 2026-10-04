"""Release build subprocesses cannot inherit private state or a drifting profile."""
from pathlib import Path
from importlib.metadata import PackageNotFoundError
import pytest

from scripts import build_desktop as builder


def test_build_environment_excludes_credentials_private_paths_and_python_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv('DISCORD_USER_TOKEN', 'synthetic-secret')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-secret')
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'private'))
    monkeypatch.setenv('PYTHONPATH', str(tmp_path / 'private-imports'))
    env = builder._isolated_build_environment(tmp_path / 'build')
    assert 'DISCORD_USER_TOKEN' not in env and 'OPENROUTER_API_KEY' not in env and 'PYTHONPATH' not in env
    assert env['HERMES_HOME'] != str(tmp_path / 'private')
    assert all(Path(env[k]).is_relative_to(tmp_path / 'build') for k in ('HOME', 'HERMES_HOME', 'XDG_CONFIG_HOME', 'TMPDIR'))
    assert env['INEBOTTEN_OFFLINE'] == '1'


@pytest.mark.parametrize('actual', [None, '2.0'])
def test_missing_or_wrong_dependency_refuses_build(tmp_path, actual):
    (tmp_path / 'requirements').mkdir()
    (tmp_path / 'requirements/desktop.lock').write_text('example-package==1.0 \\\n    --hash=sha256:' + 'a' * 64 + '\n')
    def lookup(name):
        if actual is None:
            raise PackageNotFoundError(name)
        return actual
    with pytest.raises(RuntimeError, match='desktop profile'):
        builder._ensure_desktop_profile(tmp_path, version_lookup=lookup)


def test_platform_marker_excludes_other_platform_dependencies(tmp_path):
    (tmp_path / 'requirements').mkdir()
    (tmp_path / 'requirements/desktop.lock').write_text('example-package==1.0\nwindows-only==9 ; sys_platform == "win32"\n')
    queried = []
    def lookup(name):
        queried.append(name)
        return '9' if name == 'windows-only' else '1.0'
    builder._ensure_desktop_profile(tmp_path, version_lookup=lookup)
    import sys
    assert queried == (['example-package', 'windows-only'] if sys.platform == 'win32' else ['example-package'])


def test_native_build_uses_real_repository_default_branch():
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/build-desktop-apps.yml').read_text()
    assert workflow.count('branches: [master, main]') == 2
