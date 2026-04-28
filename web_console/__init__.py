"""web_console package stubs."""

# pyright: reportUnusedImport=false

from .server import ConsoleServer
from .dashboard import render_dashboard
from .state_collector import StateCollector

__all__ = ["ConsoleServer", "render_dashboard", "StateCollector"]
__version__ = "0.1.0"
