from __future__ import annotations

from autodosie_bot.config import AppConfig
from autodosie_bot.services.base import VehicleCheckService
from autodosie_bot.services.stub import StubVehicleCheckService


def build_vehicle_check_service(config: AppConfig) -> VehicleCheckService:
    if config.vehicle_data_provider == "stub":
        return StubVehicleCheckService()

    raise RuntimeError(
        f"Unsupported VEHICLE_DATA_PROVIDER: {config.vehicle_data_provider}",
    )

