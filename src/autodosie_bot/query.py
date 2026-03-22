from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from autodosie_bot.validation import is_valid_plate, is_valid_vin, normalize_plate, normalize_vin


@dataclass(frozen=True, slots=True)
class VehicleQuery:
    kind: Literal["vin", "plate"]
    value: str


def parse_vehicle_query(raw_value: str) -> VehicleQuery | None:
    vin = normalize_vin(raw_value)
    if is_valid_vin(vin):
        return VehicleQuery(kind="vin", value=vin)

    plate = normalize_plate(raw_value)
    if is_valid_plate(plate):
        return VehicleQuery(kind="plate", value=plate)

    return None
