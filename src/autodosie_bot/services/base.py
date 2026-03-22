from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ReportSection:
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VehicleCheckReport:
    query_type: str
    query_value: str
    provider: str
    checked_at: datetime
    summary: str
    sections: tuple[ReportSection, ...]


class VehicleCheckService(Protocol):
    async def check_vin(self, vin: str) -> VehicleCheckReport:
        """Return a report for the provided VIN."""

    async def check_plate(self, plate: str) -> VehicleCheckReport:
        """Return a report for the provided vehicle plate."""


class VehicleCheckError(RuntimeError):
    """Raised when a provider cannot complete a vehicle check."""
