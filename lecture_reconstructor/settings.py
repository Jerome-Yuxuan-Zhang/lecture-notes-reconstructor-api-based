from __future__ import annotations

import json
from pathlib import Path
from typing import Any

APP_DIR = Path.home() / ".lecture_reconstructor"
SETTINGS_PATH = APP_DIR / "settings.json"
KEYRING_SERVICE = "lecture_reconstructor"


DEFAULT_SETTINGS: dict[str, Any] = {
    "input_dir": "",
    "output_root": "",
    "project_name": "lecture",
    "provider": "DeepSeek",
    "figure_provider": "Qwen",
    "base_url": "",
    "model": "",
    "api_key_env": "",
    "figure_api_key_env": "",
    "custom_providers": {},
    "temperature": 0.25,
    "max_tokens": 180000,
    "stream": False,
    "enable_vision_ocr": True,
    "batch_mode": False,
    "remember_api_key": False,
}


def load_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_SETTINGS.copy()
    settings = DEFAULT_SETTINGS.copy()
    settings.update({key: value for key, value in loaded.items() if key in settings})
    return settings


def save_settings(settings: dict[str, Any]) -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    sanitized = DEFAULT_SETTINGS.copy()
    sanitized.update({key: value for key, value in settings.items() if key in sanitized})
    sanitized.pop("api_key", None)
    SETTINGS_PATH.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
    return SETTINGS_PATH


def load_api_key(provider_name: str) -> str:
    try:
        import keyring
    except ImportError:
        return ""
    try:
        return keyring.get_password(KEYRING_SERVICE, provider_name) or ""
    except Exception:
        return ""


def save_api_key(provider_name: str, api_key: str) -> bool:
    try:
        import keyring
    except ImportError:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, provider_name, api_key)
    except Exception:
        return False
    return True


def delete_api_key(provider_name: str) -> None:
    try:
        import keyring
    except ImportError:
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, provider_name)
    except Exception:
        return
