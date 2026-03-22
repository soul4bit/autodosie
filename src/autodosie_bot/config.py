from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class BotConfig:
    token: str


@dataclass(frozen=True, slots=True)
class AppConfig:
    bot: BotConfig
    log_level: str
    vehicle_data_provider: str
    request_timeout_seconds: float
    gibdd_captcha_wait_seconds: float
    gibdd_captcha_poll_interval_seconds: float
    site_name: str
    site_url: str
    web_host: str
    web_port: int


def _load_env_file() -> None:
    env_file = os.getenv("AUTODOSIE_BOT_ENV_FILE")
    if env_file:
        load_dotenv(env_file, override=False)
        return

    load_dotenv(override=False)


def _get_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default

    try:
        return float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


def _get_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def load_config(*, require_bot_token: bool = True) -> AppConfig:
    _load_env_file()

    token = os.getenv("BOT_TOKEN", "").strip()
    if require_bot_token and not token:
        raise RuntimeError("BOT_TOKEN is not set")

    return AppConfig(
        bot=BotConfig(token=token),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        vehicle_data_provider=os.getenv("VEHICLE_DATA_PROVIDER", "free").strip().lower() or "free",
        request_timeout_seconds=_get_float("REQUEST_TIMEOUT_SECONDS", 20.0),
        gibdd_captcha_wait_seconds=_get_float("GIBDD_CAPTCHA_WAIT_SECONDS", 45.0),
        gibdd_captcha_poll_interval_seconds=_get_float("GIBDD_CAPTCHA_POLL_INTERVAL_SECONDS", 5.0),
        site_name=os.getenv("SITE_NAME", "AutoDosie").strip() or "AutoDosie",
        site_url=os.getenv("SITE_URL", "https://autodosie.ru").strip() or "https://autodosie.ru",
        web_host=os.getenv("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1",
        web_port=_get_int("WEB_PORT", 8000),
    )
