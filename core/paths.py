from __future__ import annotations

import sys
from pathlib import Path


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_runtime_path(*parts: str) -> Path:
    return app_base_dir().joinpath(*parts)


def runtime_dir() -> Path:
    return resolve_runtime_path("runtime")


def data_dir() -> Path:
    return resolve_runtime_path("data")


def logs_dir() -> Path:
    return resolve_runtime_path("logs")


def chrome_binary_path() -> Path:
    return resolve_runtime_path("runtime", "chrome", "chrome-win64", "chrome.exe")


def chromedriver_path() -> Path:
    return resolve_runtime_path("runtime", "chromedriver", "chromedriver.exe")


def chrome_user_data_dir() -> Path:
    return resolve_runtime_path("data", "profiles", "chrome-user-data")


def output_dir() -> Path:
    return resolve_runtime_path("data", "output")


def first_step_fields_output_path() -> Path:
    return output_dir() / "firstStepFields.csv"


def category_attributes_output_path() -> Path:
    return output_dir() / "categoryAttributes.csv"


def input_file_path() -> Path:
    return resolve_runtime_path("data", "input.xlsx")


def ensure_app_dirs() -> None:
    runtime_dir().mkdir(parents=True, exist_ok=True)
    resolve_runtime_path("runtime", "chrome").mkdir(parents=True, exist_ok=True)
    resolve_runtime_path("runtime", "chromedriver").mkdir(parents=True, exist_ok=True)
    data_dir().mkdir(parents=True, exist_ok=True)
    resolve_runtime_path("data", "profiles").mkdir(parents=True, exist_ok=True)
    output_dir().mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
