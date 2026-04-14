from __future__ import annotations

import logging
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from core.paths import chrome_binary_path, chromedriver_path, chrome_user_data_dir, ensure_app_dirs

logger = logging.getLogger(__name__)


class DriverStartupError(RuntimeError):
    pass


def _build_profile_dir() -> Path:
    base_profile_root = chrome_user_data_dir().parent / "chrome-user-data-runs"
    run_profile = base_profile_root / f"run-{int(time.time() * 1000)}"
    run_profile.mkdir(parents=True, exist_ok=True)
    return run_profile


def _build_options(profile_dir: Path) -> Options:
    options = Options()
    options.binary_location = str(chrome_binary_path())
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--lang=fa-IR")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-data-dir={profile_dir}")
    return options


def _launch_chrome(profile_dir: Path) -> webdriver.Chrome:
    service = Service(executable_path=str(chromedriver_path()))
    options = _build_options(profile_dir)

    try:
        return webdriver.Chrome(service=service, options=options)
    except Exception:
        try:
            service.stop()
        except Exception:
            logger.debug("Service stop after startup failure also failed", exc_info=True)
        raise


def create_driver() -> webdriver.Chrome:
    ensure_app_dirs()

    chrome_binary = chrome_binary_path()
    driver_binary = chromedriver_path()
    run_profile = _build_profile_dir()

    if not chrome_binary.exists():
        logger.error("Bundled Chrome binary not found at: %s", chrome_binary)
        raise DriverStartupError("Browser runtime files are missing. Please reinstall DKExtractor.")

    if not driver_binary.exists():
        logger.error("Bundled chromedriver not found at: %s", driver_binary)
        raise DriverStartupError("Driver runtime files are missing. Please reinstall DKExtractor.")

    logger.info("Chrome binary path: %s", chrome_binary)
    logger.info("ChromeDriver path: %s", driver_binary)
    logger.info("Chrome profile path: %s", run_profile)

    try:
        return _launch_chrome(run_profile)
    except WebDriverException as exc:
        logger.exception("Primary Chrome startup failed")
        raise DriverStartupError("Browser could not start. Close other DKExtractor/Chrome windows and try again.") from exc
    except Exception as exc:
        logger.exception("Unexpected browser startup failure")
        raise DriverStartupError("Browser startup failed unexpectedly. Please check logs and try again.") from exc
