from __future__ import annotations

import importlib.util
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
