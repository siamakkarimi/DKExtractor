from __future__ import annotations
import logging,time
from typing import Callable
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

BASE_URL="https://seller.digikala.com"
LOGIN_URL="https://seller.digikala.com/pwa/account/sign-in"
PANEL_URL="https://seller.digikala.com/pwa/"
logger=logging.getLogger(__name__)
SIGN_IN_URL_PARTS=("/pwa/account/sign-in","/account/sign-in","/sign-in")
DASHBOARD_SIGNAL_SELECTORS=[
    (By.XPATH,"//a[contains(@href,'/pwa/product/create')]"),
    (By.XPATH,"//a[contains(@href,'/pwa/products')]"),
    (By.XPATH,"//a[contains(@href,'/pwa/orders')]"),
    (By.XPATH,"//a[contains(@href,'/pwa/account/profile')]"),
    (By.XPATH,"//button[contains(normalize-space(),'\u062e\u0631\u0648\u062c')]"),
    (By.XPATH,"//*[contains(normalize-space(),'\u062f\u0627\u0634\u0628\u0648\u0631\u062f')]"),
    (By.XPATH,"//*[contains(normalize-space(),'\u06a9\u0627\u0644\u0627\u0647\u0627')]"),
    (By.XPATH,"//*[contains(normalize-space(),'\u0633\u0641\u0627\u0631\u0634')]"),
]
LOGIN_SIGNAL_SELECTORS=[
    (By.XPATH,"//input[@type='tel' or @name='username' or @name='mobile']"),
    (By.XPATH,"//input[@type='password']"),
    (By.XPATH,"//button[contains(normalize-space(),'\u0648\u0631\u0648\u062f') or contains(normalize-space(),'\u0627\u062f\u0627\u0645\u0647')]"),
    (By.XPATH,"//*[contains(normalize-space(),'\u0648\u0631\u0648\u062f') and (self::h1 or self::p or self::span or self::div)]"),
]

class SessionManager:
    def __init__(self,driver): self.driver=driver
    def _current_url(self)->str: return (self.driver.current_url or "").strip().lower()
    def _find_any(self,selectors:list[tuple[str,str]])->bool:
        try:
            for by,value in selectors:
                for element in self.driver.find_elements(by,value):
                    try:
                        if element.is_displayed(): return True
                    except Exception: continue
        except WebDriverException:
            logger.debug("Could not inspect DOM while checking session state",exc_info=True)
        return False
    def _is_blank_page(self)->bool:
        try: current_url=self._current_url()
        except WebDriverException: return True
        return current_url in {"","about:blank","data:,"}
    def _is_sign_in_page(self)->bool:
        try: current_url=self._current_url()
        except WebDriverException: return False
        return any(part in current_url for part in SIGN_IN_URL_PARTS) or self._find_any(LOGIN_SIGNAL_SELECTORS)
    def is_logged_in(self)->bool:
        try:
            current_url=self._current_url()
            if current_url in {"","about:blank","data:,"}: return False
            if any(part in current_url for part in SIGN_IN_URL_PARTS): return False
            if self._find_any(DASHBOARD_SIGNAL_SELECTORS): return True
            if self._find_any(LOGIN_SIGNAL_SELECTORS): return False
            return current_url.startswith(BASE_URL)
        except WebDriverException:
            logger.debug("Could not read current URL while checking login state",exc_info=True)
            return False
    def is_browser_open(self)->bool:
        try:
            self.driver.current_window_handle
            return True
        except WebDriverException:
            return False
    def _navigate_to_digikala(self)->None:
        logger.info("navigating to Digikala")
        self.driver.get(BASE_URL)
        time.sleep(2)
    def ensure_login(self,timeout_seconds:int=300,poll_seconds:int=2,stop_requested:Callable[[],bool]|None=None)->bool:
        self._navigate_to_digikala()
        if self._is_blank_page():
            logger.warning("Detected blank page after initial navigation; retrying Digikala")
            self._navigate_to_digikala()
        if self.is_logged_in():
            logger.info("login confirmed")
            logger.info("Session restored from persistent Chrome profile")
            return True
        logger.info("login required")
        logger.info("waiting for user login")
        self.driver.get(LOGIN_URL)
        deadline=time.time()+timeout_seconds
        while time.time()<deadline:
            if stop_requested is not None and stop_requested():
                logger.info("Login flow interrupted by stop request")
                return False
            if not self.is_browser_open():
                logger.info("Browser was closed before login completed")
                return False
            if self._is_blank_page():
                logger.warning("Detected blank page during login flow; forcing Digikala navigation")
                self._navigate_to_digikala()
                if not self.is_logged_in() and not self._is_sign_in_page():
                    logger.info("login required")
                    logger.info("waiting for user login")
                    self.driver.get(LOGIN_URL)
            if self.is_logged_in():
                logger.info("login confirmed")
                return True
            time.sleep(poll_seconds)
        logger.warning("Login timed out after %s seconds",timeout_seconds)
        raise RuntimeError("Login timed out. Please try Login Only and complete sign-in.")
    def wait_for_login_only_end(self,poll_seconds:int=1,stop_requested:Callable[[],bool]|None=None)->bool:
        while True:
            if stop_requested is not None and stop_requested():
                logger.info("Login-only flow stopped by user request")
                return True
            if not self.is_browser_open():
                logger.info("Login-only browser window was closed by the user")
                return False
            time.sleep(poll_seconds)
