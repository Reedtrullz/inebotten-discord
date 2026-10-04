from __future__ import annotations

import importlib.util
import stat
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _install_tkinter_stub(monkeypatch):
    tk = types.ModuleType("tkinter")
    ttk = types.ModuleType("tkinter.ttk")
    messagebox = types.ModuleType("tkinter.messagebox")
    scrolledtext = types.ModuleType("tkinter.scrolledtext")
    tk.Tk = object
    tk.StringVar = object
    tk.BooleanVar = object
    tk.END = "end"
    tk.ttk = ttk
    tk.messagebox = messagebox
    tk.scrolledtext = scrolledtext
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", messagebox)
    monkeypatch.setitem(sys.modules, "tkinter.scrolledtext", scrolledtext)


def _load_module(path: Path, name: str, monkeypatch):
    _install_tkinter_stub(monkeypatch)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_bundle_root(tmp_path: Path) -> Path:
    bundle_root = tmp_path / "_MEIPASS"
    scripts_dir = bundle_root / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "run_both.py").write_text("print('ok')\n", encoding="utf-8")
    return bundle_root


def test_mac_launcher_targets_scripts_run_both_in_source_tree(monkeypatch):
    module = _load_module(ROOT / "mac_app" / "launcher.py", "mac_launcher_under_test", monkeypatch)
    assert module.get_run_both_path() == ROOT / "scripts" / "run_both.py"
    assert module.get_run_both_path().exists()


def test_windows_launcher_targets_scripts_run_both_in_source_tree(monkeypatch):
    module = _load_module(ROOT / "windows_app" / "launcher.py", "windows_launcher_under_test", monkeypatch)
    assert module.get_run_both_path() == ROOT / "scripts" / "run_both.py"
    assert module.get_run_both_path().exists()


def test_mac_launcher_targets_scripts_run_both_inside_pyinstaller_bundle(monkeypatch, tmp_path):
    module = _load_module(ROOT / "mac_app" / "launcher.py", "mac_launcher_bundle_under_test", monkeypatch)
    bundle_root = _make_bundle_root(tmp_path)
    monkeypatch.setattr(module.sys, "_MEIPASS", str(bundle_root), raising=False)
    assert module.get_run_both_path() == bundle_root / "scripts" / "run_both.py"


def test_windows_launcher_targets_scripts_run_both_inside_pyinstaller_bundle(monkeypatch, tmp_path):
    module = _load_module(ROOT / "windows_app" / "launcher.py", "windows_launcher_bundle_under_test", monkeypatch)
    bundle_root = _make_bundle_root(tmp_path)
    monkeypatch.setattr(module.sys, "_MEIPASS", str(bundle_root), raising=False)
    assert module.get_run_both_path() == bundle_root / "scripts" / "run_both.py"


def test_mac_launcher_uses_self_command_when_frozen(monkeypatch, tmp_path):
    module = _load_module(ROOT / "mac_app" / "launcher.py", "mac_launcher_frozen_under_test", monkeypatch)
    bundle_root = _make_bundle_root(tmp_path)
    monkeypatch.setattr(module.sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(module.sys, "executable", "/tmp/Inebotten", raising=False)
    assert module.get_bot_command() == ["/tmp/Inebotten", "--run-bot"]


def test_windows_launcher_uses_self_command_when_frozen(monkeypatch, tmp_path):
    module = _load_module(ROOT / "windows_app" / "launcher.py", "windows_launcher_frozen_under_test", monkeypatch)
    bundle_root = _make_bundle_root(tmp_path)
    monkeypatch.setattr(module.sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(module.sys, "executable", "C:/tmp/Inebotten.exe", raising=False)
    assert module.get_bot_command() == ["C:/tmp/Inebotten.exe", "--run-bot"]


def test_mac_pyinstaller_build_bundles_scripts_directory():
    build_script = (ROOT / "mac_app" / "build.sh").read_text(encoding="utf-8")
    assert '--add-data="../scripts:scripts"' in build_script
    assert "--hidden-import=scripts" in build_script


def test_windows_pyinstaller_build_bundles_scripts_directory():
    build_script = (ROOT / "windows_app" / "build.py").read_text(encoding="utf-8")
    assert "--add-data=../scripts;scripts" in build_script
    assert "--hidden-import=scripts" in build_script


def test_desktop_launchers_preserve_unrelated_settings_and_do_not_log_tokens(monkeypatch, tmp_path):
    hermes = tmp_path / "Hermes home"
    env_path = hermes / "discord" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(
        "# preserve comment\nDISCORD_USER_TOKEN=existing-synthetic-token\n"
        "ALLOWED_USERS=123,456\nCONSOLE_API_KEY=synthetic-console-key\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)
    monkeypatch.setenv("HERMES_HOME", str(hermes))

    class Value:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    for platform in ("mac", "windows"):
        module = _load_module(ROOT / f"{platform}_app" / "launcher.py", f"{platform}_launcher_settings", monkeypatch)
        launcher = module.InebottenLauncher.__new__(module.InebottenLauncher)
        launcher.token_var = Value("")
        launcher.provider_var = Value("lm_studio")
        launcher.openrouter_key_var = Value("")
        launcher.model_var = Value("test/model")
        logs = []
        launcher._log = logs.append

        launcher._create_env_file()

        contents = env_path.read_text(encoding="utf-8")
        assert "# preserve comment\n" in contents
        assert "DISCORD_USER_TOKEN=existing-synthetic-token\n" in contents
        assert "ALLOWED_USERS=123,456\n" in contents
        assert "CONSOLE_API_KEY=synthetic-console-key\n" in contents
        assert all("synthetic" not in message for message in logs)
        assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_desktop_launchers_load_only_nonsecret_settings_from_authoritative_file(monkeypatch, tmp_path):
    hermes = tmp_path / "Hermes home"
    env_path = hermes / "discord" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(
        "DISCORD_USER_TOKEN=never-log-this-synthetic-token\n"
        "AI_PROVIDER=openrouter\nOPENROUTER_MODEL=synthetic/model\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)
    monkeypatch.setenv("HERMES_HOME", str(hermes))

    class Value:
        def __init__(self):
            self.value = None

        def set(self, value):
            self.value = value

    for platform in ("mac", "windows"):
        module = _load_module(ROOT / f"{platform}_app" / "launcher.py", f"{platform}_launcher_load", monkeypatch)
        launcher = module.InebottenLauncher.__new__(module.InebottenLauncher)
        launcher.provider_var = Value()
        launcher.model_var = Value()
        logs = []
        launcher._log = logs.append

        launcher._load_saved_config()

        assert launcher.provider_var.value == "openrouter"
        assert launcher.model_var.value == "synthetic/model"
        assert all("never-log-this-synthetic-token" not in message for message in logs)


def test_desktop_source_import_does_not_require_parent_pythonpath(tmp_path):
    import subprocess
    script = '''import runpy, sys, types
stub = types.ModuleType('tkinter')
for name in ('ttk', 'messagebox', 'scrolledtext'):
    setattr(stub, name, types.ModuleType('tkinter.'+name))
sys.modules['tkinter'] = stub
runpy.run_path(sys.argv[1], run_name='import_probe')
'''
    for platform in ('mac', 'windows'):
        result = subprocess.run([sys.executable, '-I', '-c', script, str(ROOT/f'{platform}_app/launcher.py')],
                                cwd=tmp_path, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
