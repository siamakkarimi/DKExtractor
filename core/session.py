from __future__ import annotations

import logging
import time
from typing import Callable

from selenium.common.exceptions import WebDriverException

LOGIN_URL = "https://seller.digikala.com/pwa/account/sign-in"
PANEL_URL = "https://seller.digikala.com/pwa/"

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, driver):
        self.driver = driver

    def _current_url(self) -> str:
        return (self.driver.current_url or "").lower()

    def is_logged_in(self) -> bool:
        try:
            return "login" not in self._current_url()
        except WebDriverException:
            logger.debug("Could not read current URL while checking login state", exc_info=True)
            return False

    def is_browser_open(self) -> bool:
        try:
            self.driver.current_window_handle
            return True
        except WebDriverException:
            return False

    def ensure_login(
        self,
        timeout_seconds: int = 300,
        poll_seconds: int = 2,
        stop_requested: Callable[[], bool] | None = None,
    ) -> bool:
        self.driver.get(PANEL_URL)
        time.sleep(2)

        if self.is_logged_in():
            logger.info("Session restored from persistent Chrome profile")
            return True

        logger.info("Login required. Waiting for user authentication in browser")
        self.driver.get(LOGIN_URL)

        deadline = time.time() + timeout_seconds

        while time.time() < deadline:
            if stop_requested is not None and stop_requested():
                logger.info("Login flow interrupted by stop request")
                return False

            if not self.is_browser_open():
                logger.info("Browser was closed before login completed")
                return False

            if self.is_logged_in():
                logger.info("User login completed successfully")
                return True

            time.sleep(poll_seconds)

        logger.warning("Login timed out after %s seconds", timeout_seconds)
        raise RuntimeError("Login timed out. Please try Login Only and complete sign-in.")

    def wait_for_login_only_end(
        self,
        poll_seconds: int = 1,
        stop_requested: Callable[[], bool] | None = None,
    ) -> bool:
        while True:
            if stop_requested is not None and stop_requested():
                logger.info("Login-only flow stopped by user request")
                return True

            if not self.is_browser_open():
                logger.info("Login-only browser window was closed by the user")
                return False

            time.sleep(poll_seconds)
