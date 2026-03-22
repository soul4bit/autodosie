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


def load_config() -> AppConfig:
    _load_env_file()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")

    return AppConfig(
        bot=BotConfig(token=token),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        vehicle_data_provider=os.getenv("VEHICLE_DATA_PROVIDER", "nhtsa").strip().lower() or "nhtsa",
        request_timeout_seconds=_get_float("REQUEST_TIMEOUT_SECONDS", 20.0),
        gibdd_captcha_wait_seconds=_get_float("GIBDD_CAPTCHA_WAIT_SECONDS", 45.0),
        gibdd_captcha_poll_interval_seconds=_get_float("GIBDD_CAPTCHA_POLL_INTERVAL_SECONDS", 5.0),
    )
