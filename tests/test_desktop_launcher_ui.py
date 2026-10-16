from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

from utils.openrouter_models import OpenRouterModel


ROOT = Path(__file__).resolve().parents[1]


def load_launcher(monkeypatch):
    tkinter = types.ModuleType("tkinter")
    ttk = types.ModuleType("tkinter.ttk")
    messagebox = types.ModuleType("tkinter.messagebox")
    scrolledtext = types.ModuleType("tkinter.scrolledtext")
    setattr(tkinter, "Tk", object)
    setattr(tkinter, "StringVar", object)
    setattr(tkinter, "BooleanVar", object)
    setattr(tkinter, "END", "end")
    setattr(tkinter, "ttk", ttk)
    setattr(tkinter, "messagebox", messagebox)
    setattr(tkinter, "scrolledtext", scrolledtext)
    monkeypatch.setitem(sys.modules, "tkinter", tkinter)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", messagebox)
    monkeypatch.setitem(sys.modules, "tkinter.scrolledtext", scrolledtext)
    spec = importlib.util.spec_from_file_location(
        "launcher_ui_under_test",
        ROOT / "utils" / "launcher_ui.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DesktopLauncher


class Value:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class BooleanValue:
    def __init__(self, value: bool):
        self.value = value

    def get(self) -> bool:
        return self.value

    def set(self, value: bool) -> None:
        self.value = value


class Widget:
    def __init__(self):
        self.options = {}

    def configure(self, **options):
        self.options.update(options)


def launcher_with_catalog(DesktopLauncher, models):
    launcher = DesktopLauncher.__new__(DesktopLauncher)
    launcher._main_thread = __import__("threading").get_ident()
    launcher._model_fetch_pending = True
    launcher._model_catalog = ()
    launcher._model_choices = {}
    launcher.model_var = Value("saved/model")
    launcher.model_display_var = Value()
    launcher.free_only_var = BooleanValue(False)
    launcher.model_combo = Widget()
    launcher.model_refresh_button = Widget()
    launcher.logs = []
    launcher._log = launcher.logs.append
    launcher._apply_model_catalog(True, models)
    return launcher


def test_model_catalog_populates_dropdown_and_keeps_saved_model_id(monkeypatch):
    DesktopLauncher = load_launcher(monkeypatch)
    launcher = launcher_with_catalog(DesktopLauncher, (
        OpenRouterModel(id="alpha/model", name="Alpha"),
        OpenRouterModel(id="saved/model", name="Saved"),
    ))

    assert launcher.model_combo.options == {
        "values": ("Alpha (alpha/model)", "Saved (saved/model)"),
        "state": "readonly",
    }
    assert launcher.model_display_var.get() == "Saved (saved/model)"
    assert launcher._model_fetch_pending is False
    assert launcher.logs == ["Hentet 2 modeller fra OpenRouter"]


def test_selected_dropdown_label_maps_back_to_model_id(monkeypatch):
    DesktopLauncher = load_launcher(monkeypatch)
    launcher = launcher_with_catalog(
        DesktopLauncher,
        (OpenRouterModel(id="alpha/model", name="Alpha"),),
    )
    launcher.model_display_var.set("Alpha (alpha/model)")

    launcher._on_model_selected(None)

    assert launcher.model_var.get() == "alpha/model"


def test_missing_saved_model_remains_selectable_and_failure_clears_stale_choices(monkeypatch):
    DesktopLauncher = load_launcher(monkeypatch)
    launcher = launcher_with_catalog(
        DesktopLauncher,
        (OpenRouterModel(id="alpha/model", name="Alpha"),),
    )
    assert launcher.model_display_var.get() == "Lagret modell (saved/model)"
    assert launcher._model_choices["Lagret modell (saved/model)"] == "saved/model"

    launcher._model_fetch_pending = True
    launcher._apply_model_catalog(False, ())

    assert launcher._model_choices == {}
    assert launcher.model_combo.options == {"values": (), "state": "readonly"}
    assert launcher.model_display_var.get() == "saved/model"
    assert launcher.logs[-1] == "Kunne ikke hente modeller fra OpenRouter"


def test_free_only_filter_shows_only_free_models_and_preserves_saved_paid_model(monkeypatch):
    DesktopLauncher = load_launcher(monkeypatch)
    launcher = launcher_with_catalog(DesktopLauncher, (
        OpenRouterModel(id="alpha/model", name="Alpha", is_free=False),
        OpenRouterModel(id="free/model", name="Free", is_free=True),
        OpenRouterModel(id="suffix/model:free", name="Suffix", is_free=True),
    ))

    launcher.free_only_var.set(True)
    launcher._apply_model_filter()

    assert launcher.model_combo.options["values"] == (
        "Free (free/model)",
        "Suffix (suffix/model:free)",
    )
    assert launcher.model_var.get() == "saved/model"
    assert launcher.model_display_var.get() == ""

    launcher.free_only_var.set(False)
    launcher._apply_model_filter()

    assert launcher.model_combo.options["values"] == (
        "Alpha (alpha/model)",
        "Free (free/model)",
        "Suffix (suffix/model:free)",
        "Lagret modell (saved/model)",
    )
    assert launcher.model_display_var.get() == "Lagret modell (saved/model)"
