from dataclasses import dataclass


@dataclass
class SaveEventAction:
    action: str = "SAVE_EVENT"
    title: str = ""
    date: str = ""
    time: str = ""


@dataclass
class ShowDashboardAction:
    action: str = "SHOW_DASHBOARD"


@dataclass
class NoAction:
    action: str = "NONE"
