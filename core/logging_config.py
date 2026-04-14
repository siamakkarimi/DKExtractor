from __future__ import annotations

import logging
import os
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from core.paths import app_base_dir, ensure_app_dirs, resolve_runtime_path


class UiLogHandler(logging.Handler):
    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._callback(self.format(record))
        except Exception:
            self.handleError(record)


def _has_rotating_handler(root: logging.Logger, target: Path) -> bool:
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler):
            filename = Path(getattr(handler, "baseFilename", ""))
            if filename == target:
                return True
    return False


def setup_logging(ui_callback: Callable[[str], None] | None = None) -> Path:
    ensure_app_dirs()
    log_file = resolve_runtime_path("logs", "app.log")

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not _has_rotating_handler(root, log_file):
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    if ui_callback is not None:
        already_attached = any(
            isinstance(h, UiLogHandler) and getattr(h, "_callback", None) == ui_callback
            for h in root.handlers
        )
        if not already_attached:
            ui_handler = UiLogHandler(ui_callback)
            ui_handler.setFormatter(formatter)
            root.addHandler(ui_handler)

    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("DKExtractor startup")
    logger.info("App base dir: %s", app_base_dir())
    logger.info("Working dir: %s", os.getcwd())
    logger.info("Python: %s", sys.version.replace("\n", " "))
    logger.info("Platform: %s %s", platform.system(), platform.release())
    logger.info("Frozen: %s", getattr(sys, "frozen", False))

    return log_file
