from __future__ import annotations

import logging
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
    profile_dir = chrome_user_data_dir() / "app-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir


def _profile_lock_paths(profile_dir: Path) -> list[Path]:
    return [
        profile_dir / "SingletonLock",
        profile_dir / "SingletonCookie",
        profile_dir / "SingletonSocket",
        profile_dir / "lockfile",
    ]


def _profile_lock_detected(profile_dir: Path) -> bool:
    return any(lock_path.exists() for lock_path in _profile_lock_paths(profile_dir))


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
    options.add_argument("--profile-directory=Default")
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


def _is_profile_lock_error(exc: Exception) -> bool:
    message = str(exc).lower()
    fragments = [
        "user data directory is already in use",
        "probably user data directory is already in use",
        "profile appears to be in use",
        "chrome failed to start",
        "devtoolsactiveport",
        "session not created",
    ]
    return any(fragment in message for fragment in fragments)


def create_driver() -> webdriver.Chrome:
    ensure_app_dirs()

    chrome_binary = chrome_binary_path()
    driver_binary = chromedriver_path()
    profile_dir = _build_profile_dir()

    if not chrome_binary.exists():
        logger.error("Bundled Chrome binary not found at: %s", chrome_binary)
        raise DriverStartupError("Browser runtime files are missing. Please reinstall DKExtractor.")

    if not driver_binary.exists():
        logger.error("Bundled chromedriver not found at: %s", driver_binary)
        raise DriverStartupError("Driver runtime files are missing. Please reinstall DKExtractor.")

    logger.info("Chrome binary path: %s", chrome_binary)
    logger.info("ChromeDriver path: %s", driver_binary)
    logger.info("Chrome profile path: %s", profile_dir)

    if _profile_lock_detected(profile_dir):
        logger.warning("Chrome profile lock files detected at: %s", profile_dir)

    try:
        return _launch_chrome(profile_dir)
    except WebDriverException as exc:
        if _is_profile_lock_error(exc):
            logger.exception("Chrome startup failed because the app profile is in use")
            raise DriverStartupError(
                "The DKExtractor browser profile is already in use. Close other DKExtractor browser windows and try again."
            ) from exc
        logger.exception("Primary Chrome startup failed")
        raise DriverStartupError("Browser could not start. Close other DKExtractor/Chrome windows and try again.") from exc
    except Exception as exc:
        if _is_profile_lock_error(exc):
            logger.exception("Chrome startup failed because the app profile is in use")
            raise DriverStartupError(
                "The DKExtractor browser profile is already in use. Close other DKExtractor browser windows and try again."
            ) from exc
        logger.exception("Unexpected browser startup failure")
        raise DriverStartupError("Browser startup failed unexpectedly. Please check logs and try again.") from exc
