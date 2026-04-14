from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Event

from PySide6.QtCore import QObject, Signal

from core.driver import DriverStartupError, create_driver
from core.extractor import Extractor
from core.session import SessionManager

logger = logging.getLogger(__name__)


@dataclass
class ExtractionTask:
    name: str
    url: str


class ExtractionWorker(QObject):
    progress = Signal(int, int)
    row_status = Signal(int, str, str, str)
    log = Signal(str)
    finished = Signal(int, int, int, bool)
    failed = Signal(str)

    def __init__(self, tasks: list[ExtractionTask], login_only: bool = False):
        super().__init__()
        self._tasks = tasks
        self._login_only = login_only
        self._stop_event = Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def is_stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def run(self) -> None:
        driver = None
        total = len(self._tasks)
        success_count = 0
        fail_count = 0
        stopped = False

        if not self._login_only:
            self.progress.emit(0, total)

        try:
            self.log.emit("Launching browser runtime...")
            logger.info("Launching browser runtime")
            driver = create_driver()

            if self.is_stop_requested():
                stopped = True
                self.log.emit("Stop requested before login.")
                return

            session = SessionManager(driver)
            self.log.emit("Checking login session...")
            logged_in = session.ensure_login(stop_requested=self.is_stop_requested)

            if not logged_in:
                stopped = True
                self.log.emit("Stopped during login.")
                return

            if self._login_only:
                success_count = 1
                self.progress.emit(1, 1)
                self.log.emit("Login successful. Browser will stay open until you click Stop or close it.")
                stopped = session.wait_for_login_only_end(stop_requested=self.is_stop_requested)

                if stopped:
                    self.log.emit("Login-only flow stopped by user.")
                else:
                    self.log.emit("Login-only browser was closed after successful login.")
                return

            extractor = Extractor(driver)

            for index, task in enumerate(self._tasks):
                if self.is_stop_requested():
                    stopped = True
                    self.log.emit("Stop requested by user.")
                    logger.info("Stop requested at task index %s", index)
                    break

                self.row_status.emit(index, "Running", "", "")
                self.log.emit(f"Processing {index + 1}/{total}: {task.name}")
                logger.info("Processing %s/%s | %s", index + 1, total, task.url)

                loaded = False
                last_error = ""

                for _ in range(3):
                    if self.is_stop_requested():
                        stopped = True
                        break
                    try:
                        driver.get(task.url)
                        loaded = True
                        break
                    except Exception as exc:
                        last_error = str(exc)
                        logger.warning("Navigation retry for %s: %s", task.url, last_error)
                        time.sleep(2)

                if stopped:
                    break

                if not loaded:
                    fail_count += 1
                    self.row_status.emit(index, "Failed", "", "Navigation failed after 3 retries")
                    self.progress.emit(index + 1, total)
                    logger.error("Navigation failed for %s | last_error=%s", task.url, last_error)
                    continue

                try:
                    step2, step3 = extractor.extract_product(task.name)
                    extractor.save(task.name, step2, step3)
                    self.log.emit(
                        f"Extracted {task.name}: step2 general-info fields={len(step2)}, "
                        f"step3 specification fields={len(step3)}"
                    )
                    success_count += 1
                    self.row_status.emit(index, "Success", "Saved", "")
                except Exception as exc:
                    fail_count += 1
                    self.row_status.emit(index, "Failed", "", "Extraction error")
                    logger.exception("Task failed for %s: %s", task.url, str(exc))

                self.progress.emit(index + 1, total)

        except DriverStartupError as exc:
            logger.exception("Driver startup failed")
            self.failed.emit(str(exc))
        except Exception as exc:
            logger.exception("Worker fatal error")
            self.failed.emit("A fatal error happened during extraction. Please check logs.")
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    logger.exception("Failed to close browser")

            self.finished.emit(total, success_count, fail_count, stopped)
