from __future__ import annotations

import os
from pathlib import Path

DEFAULT_BROWSER = "chrome"

BROWSER_META = {
    "chrome": {
        "label": "Chrome",
        "playwright_channel": "chrome",
        "config_key": "chrome_profile_path",
        "user_data_parts": ("Google", "Chrome", "User Data"),
        "dedicated_dir": "chrome-profile",
    },
    "edge": {
        "label": "Edge",
        "playwright_channel": "msedge",
        "config_key": "edge_profile_path",
        "user_data_parts": ("Microsoft", "Edge", "User Data"),
        "dedicated_dir": "edge-profile",
    },
}


def normalize_browser(browser: str | None) -> str:
    candidate = (browser or DEFAULT_BROWSER).strip().lower()
    return candidate if candidate in BROWSER_META else DEFAULT_BROWSER


def iter_browser_keys() -> tuple[str, ...]:
    return tuple(BROWSER_META.keys())


def get_browser_label(browser: str | None) -> str:
    return BROWSER_META[normalize_browser(browser)]["label"]


def get_playwright_channel(browser: str | None) -> str:
    return BROWSER_META[normalize_browser(browser)]["playwright_channel"]


def get_profile_config_key(browser: str | None) -> str:
    return BROWSER_META[normalize_browser(browser)]["config_key"]


def get_personal_user_data_dir(browser: str | None) -> Path:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    return local_app_data.joinpath(*BROWSER_META[normalize_browser(browser)]["user_data_parts"])


def get_personal_default_profile_dir(browser: str | None) -> Path:
    return get_personal_user_data_dir(browser) / "Default"


def get_dedicated_profile_path(browser: str | None) -> str:
    base_dir = Path(os.getenv("PTX_RUNTIME_DIR", Path(__file__).resolve().parent))
    dedicated_dir = BROWSER_META[normalize_browser(browser)]["dedicated_dir"]
    return str(base_dir / "data" / dedicated_dir)


def is_main_user_data_dir(path: str | None, browser: str | None) -> bool:
    if not path:
        return False
    try:
        return Path(path).resolve() == get_personal_user_data_dir(browser).resolve()
    except Exception:
        return False
