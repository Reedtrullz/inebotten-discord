from pathlib import Path

from utils.logger import LogBuffer, redact_sensitive, setup_logger


def test_redact_sensitive_removes_common_credentials():
    text = (
        "DISCORD_USER_TOKEN=abc.def.abcdefghijklmnopqrstuv "
        "Authorization: bearer-secret "
        "OPENROUTER_API_KEY=sk-secret"
    )
    redacted = redact_sensitive(text)
    assert "abc.def.abcdefghijklmnopqrstuv" not in redacted
    assert "bearer-secret" not in redacted
    assert "sk-secret" not in redacted
    assert "[REDACTED]" in redacted


def test_log_buffer_redacts_before_persistence(monkeypatch):
    buffer = LogBuffer()
    captured: list[str] = []

    class Store:
        def append_logs(self, lines):
            captured.extend(lines)

        def load_logs(self, count):
            return captured[-count:]

    monkeypatch.setattr(buffer, "_lazy_store", lambda: Store())
    buffer.append("DISCORD_USER_TOKEN=abc.def.abcdefghijklmnopqrstuv")
    assert captured == ["DISCORD_USER_TOKEN=[REDACTED]"]
    assert buffer.get_lines(1) == ["DISCORD_USER_TOKEN=[REDACTED]"]


def test_setup_logger_creates_private_log_files(tmp_path: Path):
    logger = setup_logger(f"logger-hardening-{tmp_path.name}", log_dir=tmp_path)
    logger.info("DISCORD_USER_TOKEN=abc.def.abcdefghijklmnopqrstuv")
    log_path = tmp_path / "inebotten.log"
    assert log_path.exists()
    assert log_path.stat().st_mode & 0o777 == 0o600
    assert "abc.def.abcdefghijklmnopqrstuv" not in log_path.read_text(encoding="utf-8")
