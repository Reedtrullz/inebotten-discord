"""Install isolation before pytest/plugin/application imports in the safe runner."""

import os

if os.environ.get("INEBOTTEN_OFFLINE_TESTS") == "1":
    import inebotten_offline  # noqa: F401
