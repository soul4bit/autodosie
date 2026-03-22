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
    vin: str
    provider: str
    checked_at: datetime
    summary: str
    sections: tuple[ReportSection, ...]


class VehicleCheckService(Protocol):
    async def check_vin(self, vin: str) -> VehicleCheckReport:
        """Return a report for the provided VIN."""

