from __future__ import annotations

import logging
import time
from typing import Callable

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

LOGIN_URL = "https://seller.digikala.com/pwa/account/sign-in"
PANEL_URL = "https://seller.digikala.com/pwa/"

logger = logging.getLogger(__name__)

SIGN_IN_URL_PARTS = ("/account/sign-in", "/sign-in")
AUTHENTICATED_SIGNAL_SELECTORS = [
    (By.XPATH, "//a[contains(@href,'/pwa/product/create')]"),
    (By.XPATH, "//a[contains(@href,'/pwa/products')]"),
    (By.XPATH, "//a[contains(@href,'/pwa/orders')]"),
    (By.XPATH, "//a[contains(@href,'/pwa/account/profile')]"),
    (By.XPATH, "//button[contains(normalize-space(),'خروج')]"),
    (By.XPATH, "//*[contains(normalize-space(),'داشبورد')]"),
    (By.XPATH, "//*[contains(normalize-space(),'کالاها')]"),
    (By.XPATH, "//*[contains(normalize-space(),'سفارش')]"),
]
LOGIN_SIGNAL_SELECTORS = [
    (By.XPATH, "//input[@type='tel' or @name='username' or @name='mobile']"),
    (By.XPATH, "//input[@type='password']"),
    (By.XPATH, "//button[contains(normalize-space(),'ورود') or contains(normalize-space(),'ادامه')]"),
    (By.XPATH, "//*[contains(normalize-space(),'ورود') and (self::h1 or self::p or self::span or self::div)]"),
]


class SessionManager:
    def __init__(self, driver):
        self.driver = driver

    def _current_url(self) -> str:
        return (self.driver.current_url or "").lower()

    def _find_any(self, selectors: list[tuple[str, str]]) -> bool:
        try:
            for by, value in selectors:
                for element in self.driver.find_elements(by, value):
                    try:
                        if element.is_displayed():
                            return True
                    except Exception:
                        continue
        except WebDriverException:
            logger.debug("Could not inspect DOM while checking authentication state", exc_info=True)
        return False

    def _is_sign_in_page(self) -> bool:
        try:
            current_url = self._current_url()
        except WebDriverException:
            return False

        if any(part in current_url for part in SIGN_IN_URL_PARTS):
            return True
        return self._find_any(LOGIN_SIGNAL_SELECTORS)

    def is_logged_in(self) -> bool:
        try:
            current_url = self._current_url()
            if self._is_sign_in_page():
                return False

            if any(part in current_url for part in ("/pwa/product/", "/pwa/orders", "/pwa/account/profile")):
                return True

            return self._find_any(AUTHENTICATED_SIGNAL_SELECTORS)
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

        logger.info("Authentication required. Waiting for user sign-in in browser")
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
