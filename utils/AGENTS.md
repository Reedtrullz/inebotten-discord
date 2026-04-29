# utils/ — Shared Utilities

Cross-cutting helpers used by multiple modules.

## STRUCTURE

```
utils/
├── logger.py           # Structured logging, LogBuffer, install_log_capture
├── sanitizer.py        # Input sanitization helpers
├── secure_storage.py   # Encrypted credential storage
└── setup.py            # First-run setup wizard
```

## WHERE TO LOOK

| Task | File |
|------|------|
| Change logging | `logger.py` |
| Change log capture | `logger.py` — `LogBuffer`, `BufferHandler`, `StdoutWrapper` |
| Change credential storage | `secure_storage.py` |
| Change input sanitization | `sanitizer.py` |

## NOTES

- `LogBuffer` is in-memory deque backed by persistent JSONL via `ConsoleStore`
- `install_log_capture()` redirects both logging and stdout to `LogBuffer`
- `secure_storage.py` falls back to encrypted file if keyring is unavailable
