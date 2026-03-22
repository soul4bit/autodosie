from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from autodosie_bot.services.base import ReportSection, VehicleCheckError, VehicleCheckReport
from autodosie_bot.services.stub import StubVehicleCheckService


class NhtsaVehicleCheckService:
    def __init__(self, timeout_seconds: float) -> None:
        self._timeout = timeout_seconds
        self._plate_fallback = StubVehicleCheckService()

    async def check_plate(self, plate: str) -> VehicleCheckReport:
        return await self._plate_fallback.check_plate(plate)

    async def check_vin(self, vin: str) -> VehicleCheckReport:
        result = await self._decode_vin(vin)
        sections = self._build_sections(vin, result)

        has_identity = any(result.get(name) for name in ("Make", "Model", "ModelYear", "Manufacturer"))
        error_text = self._clean(result.get("ErrorText"))
        note = self._clean(result.get("Note"))

        if has_identity:
            summary = "Найдены базовые сведения об автомобиле по VIN."
        elif error_text:
            summary = "Источник вернул ограниченные сведения по VIN."
        else:
            summary = "Источник вернул частичные сведения по VIN."

        if note and "non-u.s. market vehicles" in note.lower():
            summary += " Для неамериканских автомобилей данные могут быть неполными."

        return VehicleCheckReport(
            query_type="vin",
            query_value=vin,
            provider="nhtsa-vpic",
            checked_at=datetime.now(tz=timezone.utc),
            summary=summary,
            sections=tuple(sections),
        )

    async def _decode_vin(self, vin: str) -> dict[str, str]:
        url = (
            "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/"
            f"{quote(vin)}?format=json"
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "autodosie-web/0.1"},
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise VehicleCheckError("Источник VIN отвечает слишком долго. Повтори запрос позже.") from exc
        except httpx.HTTPError as exc:
            raise VehicleCheckError("Не удалось получить ответ от источника VIN.") from exc

        try:
            payload = response.json()
            results = payload["Results"]
            if not results:
                raise VehicleCheckError("Источник VIN не вернул данных по запросу.")
            raw_result = results[0]
        except VehicleCheckError:
            raise
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise VehicleCheckError("Источник VIN вернул неожиданный формат ответа.") from exc

        return {
            str(key): "" if value is None else str(value).strip()
            for key, value in raw_result.items()
        }

    def _build_sections(self, vin: str, result: dict[str, str]) -> list[ReportSection]:
        sections: list[ReportSection] = []

        main_lines = self._collect_lines(
            result,
            (
                ("Марка", "Make"),
                ("Модель", "Model"),
                ("Год модели", "ModelYear"),
                ("Комплектация", "Trim"),
                ("Серия", "Series"),
                ("Тип ТС", "VehicleType"),
                ("Кузов", "BodyClass"),
            ),
        )
        if main_lines:
            sections.append(ReportSection(title="Основное", lines=tuple(main_lines)))

        technical_lines = self._collect_lines(
            result,
            (
                ("Двигатель", "EngineModel"),
                ("Конфигурация двигателя", "EngineConfiguration"),
                ("Цилиндры", "EngineCylinders"),
                ("Объем, л", "DisplacementL"),
                ("Топливо", "FuelTypePrimary"),
                ("Привод", "DriveType"),
                ("КПП", "TransmissionStyle"),
                ("Передач", "TransmissionSpeeds"),
                ("Двери", "Doors"),
            ),
        )
        if technical_lines:
            sections.append(ReportSection(title="Техника", lines=tuple(technical_lines)))

        manufacturer_lines = [f"WMI: {vin[:3]}"]
        manufacturer_lines.extend(
            self._collect_lines(
                result,
                (
                    ("Производитель", "Manufacturer"),
                    ("Страна сборки", "PlantCountry"),
                    ("Город сборки", "PlantCity"),
                    ("Дескриптор", "VehicleDescriptor"),
                ),
            ),
        )
        sections.append(ReportSection(title="Происхождение", lines=tuple(manufacturer_lines)))

        notes_lines = self._collect_lines(
            result,
            (
                ("Ошибка декодирования", "ErrorText"),
                ("Примечание источника", "Note"),
            ),
        )
        if notes_lines:
            sections.append(ReportSection(title="Примечания", lines=tuple(notes_lines)))

        if not sections:
            sections.append(
                ReportSection(
                    title="Результат",
                    lines=("Источник не вернул распознаваемых полей по этому VIN.",),
                ),
            )

        sections.append(
            ReportSection(
                title="Источник данных",
                lines=(
                    "базовая расшифровка VIN через официальный API NHTSA vPIC",
                    "для части неамериканских автомобилей данные могут быть неполными",
                    "проверки ГИБДД по ограничениям, розыску и регистрациям потребуют отдельной интеграции с капчей",
                ),
            ),
        )

        return sections

    def _collect_lines(
        self,
        result: dict[str, str],
        mapping: tuple[tuple[str, str], ...],
    ) -> list[str]:
        lines: list[str] = []

        for label, key in mapping:
            value = self._clean(result.get(key))
            if value:
                lines.append(f"{label}: {value}")

        return lines

    def _clean(self, value: str | None) -> str:
        if value is None:
            return ""
        cleaned = value.strip()
        if cleaned in {"", "0", "Not Applicable", "null"}:
            return ""
        return cleaned
