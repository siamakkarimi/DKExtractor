from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.logging_config import setup_logging


def _handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    logger = logging.getLogger(__name__)
    logger.exception("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


def main() -> int:
    setup_logging()
    sys.excepthook = _handle_uncaught_exception

    logger = logging.getLogger(__name__)

    try:
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError:
        message = (
            "PySide6 is not installed. Install dependencies with "
            "'python -m pip install -r requirements.txt'."
        )
        logger.error(message)
        print(message)
        return 1

    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
