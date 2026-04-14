from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.logging_config import setup_logging
from core.input_validation import InputValidationError, load_tasks_from_excel
from core.paths import ensure_app_dirs, input_file_path, logs_dir, output_dir
from core.worker import ExtractionTask, ExtractionWorker

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DKExtractor")
        self.resize(1200, 760)

        self.tasks: list[ExtractionTask] = []
        self.worker_thread: QThread | None = None
        self.worker: ExtractionWorker | None = None
        self._job_failed = False
        self._active_login_only = False

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Path to input.xlsx")
        self.path_input.setText(str(input_file_path()))

        self.btn_browse = QPushButton("Load Excel")
        self.btn_start = QPushButton("Start Extraction")
        self.btn_stop = QPushButton("Stop")
        self.btn_login_only = QPushButton("Login Only")
        self.btn_output = QPushButton("Open Output")
        self.btn_logs = QPushButton("Open Logs")

        self.summary_label = QLabel("Ready")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "URL", "Status", "Result", "Error"])
        self.table.horizontalHeader().setStretchLastSection(True)

        self.log_panel = QTextEdit()
        self.log_panel.setReadOnly(True)

        top_row = QHBoxLayout()
        top_row.addWidget(self.path_input)
        top_row.addWidget(self.btn_browse)

        actions_row = QHBoxLayout()
        actions_row.addWidget(self.btn_start)
        actions_row.addWidget(self.btn_stop)
        actions_row.addWidget(self.btn_login_only)
        actions_row.addWidget(self.btn_output)
        actions_row.addWidget(self.btn_logs)

        layout = QVBoxLayout()
        layout.addLayout(top_row)
        layout.addLayout(actions_row)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.table)
        layout.addWidget(self.log_panel)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        ensure_app_dirs()
        setup_logging(self.append_log)
        logger.info("Application started")

        self.btn_browse.clicked.connect(self.pick_file)
        self.btn_start.clicked.connect(self.start_extraction)
        self.btn_stop.clicked.connect(self.stop_extraction)
        self.btn_login_only.clicked.connect(self.run_login_only)
        self.btn_output.clicked.connect(self.open_output)
        self.btn_logs.clicked.connect(self.open_logs)

        self._set_idle_state()
        self.load_tasks_if_exists()

    def append_log(self, message: str) -> None:
        self.log_panel.append(message)

    def _set_idle_state(self) -> None:
        self.btn_browse.setEnabled(True)
        self.path_input.setEnabled(True)
        self.btn_start.setEnabled(True)
        self.btn_login_only.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def _set_running_state(self) -> None:
        self.btn_browse.setEnabled(False)
        self.path_input.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.btn_login_only.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def pick_file(self) -> None:
        start_dir = str(Path(self.path_input.text().strip()).parent)
        path, _ = QFileDialog.getOpenFileName(self, "Select input file", start_dir, "Excel Files (*.xlsx)")
        if path:
            self.path_input.setText(path)
            self.load_tasks(path)

    def load_tasks_if_exists(self) -> None:
        candidate = Path(self.path_input.text().strip())
        if candidate.exists():
            self.load_tasks(str(candidate))

    def load_tasks(self, path: str) -> bool:
        try:
            file_path = Path(path)
            rows, invalid_rows = load_tasks_from_excel(file_path)
            tasks = [ExtractionTask(name=name, url=url) for name, url in rows]

            self.tasks = tasks
            self.table.setRowCount(len(self.tasks))
            for i, task in enumerate(self.tasks):
                self.table.setItem(i, 0, QTableWidgetItem(task.name))
                self.table.setItem(i, 1, QTableWidgetItem(task.url))
                self.table.setItem(i, 2, QTableWidgetItem("Pending"))
                self.table.setItem(i, 3, QTableWidgetItem(""))
                self.table.setItem(i, 4, QTableWidgetItem(""))

            message = f"Loaded {len(self.tasks)} items"
            if invalid_rows:
                message += f" ({invalid_rows} invalid rows skipped)"

            self.summary_label.setText(message)
            self.append_log(f"Loaded input file: {file_path}")
            logger.info("Loaded input file: %s | valid=%s invalid=%s", file_path, len(tasks), invalid_rows)
            return True
        except (InputValidationError, Exception) as exc:
            self.tasks = []
            self.table.setRowCount(0)
            self.summary_label.setText("Input validation failed")
            QMessageBox.critical(self, "Input Error", str(exc))
            logger.exception("Failed to load/validate input file")
            return False

    def start_extraction(self) -> None:
        if self.worker_thread is not None:
            QMessageBox.warning(self, "Busy", "An extraction job is already running.")
            return

        path = self.path_input.text().strip()
        if not self.load_tasks(path):
            return

        self._job_failed = False
        self.progress.setRange(0, len(self.tasks))
        self.progress.setValue(0)
        self._start_worker(login_only=False)

    def run_login_only(self) -> None:
        if self.worker_thread is not None:
            QMessageBox.warning(self, "Busy", "Another job is already running.")
            return

        self._job_failed = False
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._start_worker(login_only=True)

    def _start_worker(self, login_only: bool) -> None:
        worker_tasks = [] if login_only else self.tasks

        self.worker_thread = QThread(self)
        self.worker = ExtractionWorker(worker_tasks, login_only=login_only)
        self._active_login_only = login_only
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.row_status.connect(self.on_row_status)
        self.worker.log.connect(self.append_log)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)

        self.worker.finished.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.cleanup_worker)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self._set_running_state()
        self.summary_label.setText("Running...")
        self.worker_thread.start()

    def stop_extraction(self) -> None:
        if self.worker is not None:
            self.worker.request_stop()
            self.btn_stop.setEnabled(False)
            self.summary_label.setText("Stopping...")
            self.append_log("Stop requested, finishing current safe step...")

    def on_progress(self, current: int, total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(current)
        self.summary_label.setText(f"Progress: {current}/{total}")

    def on_row_status(self, row: int, status: str, result: str, error: str) -> None:
        if row < self.table.rowCount():
            self.table.setItem(row, 2, QTableWidgetItem(status))
            self.table.setItem(row, 3, QTableWidgetItem(result))
            self.table.setItem(row, 4, QTableWidgetItem(error))

    def on_finished(self, total: int, success: int, failed: int, stopped: bool) -> None:
        if self.progress.maximum() > 0 and not stopped:
            self.progress.setValue(self.progress.maximum())

        if self._active_login_only and stopped:
            self.summary_label.setText("Login Only stopped")
            self.append_log("Login Only stopped by user.")
        elif self._active_login_only and not self._job_failed:
            self.summary_label.setText("Login Only completed")
            self.append_log("Login Only completed after successful login.")
        elif stopped:
            self.summary_label.setText(f"Stopped | success={success} failed={failed}")
            self.append_log(f"Job stopped by user. success={success}, failed={failed}")
        elif self._job_failed:
            self.summary_label.setText("Finished with fatal error")
            self.append_log("Job finished with fatal error. Review logs for details.")
        else:
            self.summary_label.setText(f"Finished | total={total} success={success} failed={failed}")
            self.append_log(f"Finished job: total={total}, success={success}, failed={failed}")

    def on_failed(self, error: str) -> None:
        self._job_failed = True
        self.append_log(f"Fatal error: {error}")
        QMessageBox.critical(self, "Fatal Error", error)

    def cleanup_worker(self) -> None:
        self._set_idle_state()
        self._active_login_only = False
        self.worker = None
        self.worker_thread = None

    def open_output(self) -> None:
        ensure_app_dirs()
        os.startfile(str(output_dir()))

    def open_logs(self) -> None:
        ensure_app_dirs()
        os.startfile(str(logs_dir()))

    def closeEvent(self, event):  # noqa: N802
        if self.worker_thread is not None:
            QMessageBox.warning(self, "Running", "Stop the current job before closing the app.")
            event.ignore()
            return
        super().closeEvent(event)
