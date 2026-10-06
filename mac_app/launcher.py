#!/usr/bin/env python3
"""Inebotten desktop launcher and explicit isolated worker entrypoints."""
import sys
from pathlib import Path

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == '__main__':
    if '--smoke-artifact' in sys.argv[1:]:
        from scripts.smoke_release_artifact import main as smoke
        raise SystemExit(smoke())
    from utils.launcher_entrypoints import dispatch_worker
    dispatch_worker()

import tkinter as tk
from tkinter import messagebox
from utils.launcher_ui import DesktopLauncher
from utils.launcher_entrypoints import worker_command, bundle_root


def get_project_root() -> Path:
    return bundle_root()


def get_run_both_path() -> Path:
    return get_project_root() / 'scripts' / 'run_both.py'


def get_bot_command() -> list[str]:
    return worker_command('--run-bot', Path(__file__).resolve())


class InebottenLauncher(DesktopLauncher):
    def __init__(self, root, *, controller=None):
        super().__init__(root, command=get_bot_command, project_root=get_project_root, controller=controller)


def main():
    from utils.launcher_entrypoints import configure_source_tk
    configure_source_tk()
    root=tk.Tk()
    InebottenLauncher(root)
    root.mainloop()


if __name__ == '__main__':
    main()
