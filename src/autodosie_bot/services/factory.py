from __future__ import annotations

from autodosie_bot.config import AppConfig
from autodosie_bot.services.base import VehicleCheckService
from autodosie_bot.services.free_report import FreeVehicleCheckService
from autodosie_bot.services.gibdd import GibddCheckService
from autodosie_bot.services.nhtsa import NhtsaVehicleCheckService
from autodosie_bot.services.stub import StubVehicleCheckService


def build_vehicle_check_service(config: AppConfig) -> VehicleCheckService:
    if config.vehicle_data_provider == "stub":
        return StubVehicleCheckService()

    if config.vehicle_data_provider == "nhtsa":
        return NhtsaVehicleCheckService(timeout_seconds=config.request_timeout_seconds)

    if config.vehicle_data_provider == "free":
        return FreeVehicleCheckService(timeout_seconds=config.request_timeout_seconds)

    raise RuntimeError(
        f"Unsupported VEHICLE_DATA_PROVIDER: {config.vehicle_data_provider}",
    )


def build_gibdd_check_service(config: AppConfig) -> GibddCheckService:
    return GibddCheckService(
        timeout_seconds=config.request_timeout_seconds,
        captcha_wait_seconds=config.gibdd_captcha_wait_seconds,
        captcha_poll_interval_seconds=config.gibdd_captcha_poll_interval_seconds,
    )
