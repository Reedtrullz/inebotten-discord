#!/usr/bin/env python3
"""
Structured Logging Module
Provides centralized logging configuration for the Inebotten Discord bot
"""

import logging
import sys
from collections import deque
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional


def setup_logger(
    name: str,
    log_level: str = "INFO",
    log_to_file: bool = True,
    log_dir: Optional[Path] = None
) -> logging.Logger:
    """
    Setup structured logger with console and file output
    
    Args:
        name: Logger name (usually __name__)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Whether to log to file
        log_dir: Directory for log files (defaults to ~/.hermes/discord/logs)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    # Create formatters
    console_format = logging.Formatter(
        '%(asctime)s [%(levelname)8s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    file_format = logging.Formatter(
        '%(asctime)s [%(levelname)8s] [%(name)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler with rotation
    if log_to_file:
        if log_dir is None:
            log_dir = Path.home() / '.hermes' / 'discord' / 'logs'
        
        log_dir.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            log_dir / 'inebotten.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance (convenience function)
    
    Args:
        name: Logger name (usually __name__)
    
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def set_log_level(level: str):
    """
    Set the global log level
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    logging.getLogger().setLevel(getattr(logging, level.upper()))


class LogBuffer:
    def __init__(self, maxlen: int = 2000):
        self._buffer: deque[str] = deque(maxlen=maxlen)
        self._store = None

    def _lazy_store(self):
        if self._store is None:
            try:
                from web_console.console_store import get_console_store
                self._store = get_console_store()
            except Exception:
                pass
        return self._store

    def append(self, line: str) -> None:
        self._buffer.append(line)
        store = self._lazy_store()
        if store is not None:
            store.append_logs([line])

    def get_lines(self, count: int = 200) -> list[str]:
        store = self._lazy_store()
        if store is not None:
            persisted = store.load_logs(count)
            live = list(self._buffer)
            combined = persisted + live
            return combined[-count:]
        return list(self._buffer)[-count:]


class BufferHandler(logging.Handler):
    def __init__(self, buffer: LogBuffer):
        super().__init__()
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._buffer.append(self.format(record))
        except Exception:
            pass


class StdoutWrapper:
    def __init__(self, stream, buffer: LogBuffer):
        self._stream = stream
        self._buffer = buffer
        self._pending = ""

    def write(self, data: str) -> None:
        self._stream.write(data)
        self._pending += data
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._buffer.append(line)

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        return getattr(self._stream, "isatty", lambda: False)()

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


_log_buffer = LogBuffer()


def get_log_buffer() -> LogBuffer:
    return _log_buffer


def install_log_capture() -> None:
    buffer = get_log_buffer()

    root = logging.getLogger()
    handler = BufferHandler(buffer)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)8s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
    root.addHandler(handler)

    sys.stdout = StdoutWrapper(sys.stdout, buffer)
    sys.stderr = StdoutWrapper(sys.stderr, buffer)


class LoggerMixin:
    """
    Mixin class to add logging capabilities to any class
    """

    @property
    def logger(self) -> logging.Logger:
        """Get logger for this class"""
        if not hasattr(self, '_logger'):
            self._logger = logging.getLogger(self.__class__.__name__)
        return self._logger
