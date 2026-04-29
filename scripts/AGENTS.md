# scripts/ — Entry Points and Operations

Runtime entry points, deployment helpers, release automation, and utility scripts.

## STRUCTURE

```
scripts/
├── run_both.py              # Main entry: bridge + selfbot together
├── start_selfbot.py         # Selfbot only
├── selfbot_runner.py        # Selfbot launcher wrapper
├── run_tests.sh             # Test runner script
├── run_web_console_qa.py    # Console QA automation
├── auth_gcal.py             # Google Calendar OAuth setup
├── write_version.py         # Version bump helper
├── create-release.sh        # Release build script
├── deploy/                  # VPS deployment scripts
│   ├── install-autoupdate.sh
│   └── ...
└── quickstart.sh            # Quick start helper
```

## WHERE TO LOOK

| Task | File |
|------|------|
| Start bot | `run_both.py` or `start_selfbot.py` |
| Deploy to VPS | `deploy/install-autoupdate.sh` |
| Run tests | `run_tests.sh` |
| Set up GCal | `auth_gcal.py` |
| Build release | `create-release.sh` |

## NOTES

- `run_both.py` is the primary production entry point
- `setup.py` in repo root is an interactive first-run wizard, not a packaging file
- `deploy/` contains VPS auto-update and webhook scripts
