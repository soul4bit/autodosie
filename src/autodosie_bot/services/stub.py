from __future__ import annotations

from datetime import datetime, timezone

from autodosie_bot.services.base import ReportSection, VehicleCheckReport


class StubVehicleCheckService:
    async def check_vin(self, vin: str) -> VehicleCheckReport:
        return VehicleCheckReport(
            query_type="vin",
            query_value=vin,
            provider="stub",
            checked_at=datetime.now(tz=timezone.utc),
            summary=(
                "Каркас запроса работает. Сейчас ответ формируется заглушкой, "
                "чтобы проверить сценарий бота и деплой."
            ),
            sections=(
                ReportSection(
                    title="Что уже готово",
                    lines=(
                        "бот принимает и валидирует VIN",
                        "деплой обновляет код на VPS по git push",
                        "можно безопасно подключать реальный provider следующим этапом",
                    ),
                ),
                ReportSection(
                    title="Следующий этап",
                    lines=(
                        "подключить SQLite для пользователей и истории запросов",
                        "реализовать provider для реального источника данных",
                        "добавить обработку ошибок и ограничение частоты запросов",
                    ),
                ),
            ),
        )

    async def check_plate(self, plate: str) -> VehicleCheckReport:
        return VehicleCheckReport(
            query_type="plate",
            query_value=plate,
            provider="stub",
            checked_at=datetime.now(tz=timezone.utc),
            summary=(
                "Госномер распознан, но реальный источник для поиска VIN по номеру "
                "пока не подключен."
            ),
            sections=(
                ReportSection(
                    title="Что уже готово",
                    lines=(
                        "бот умеет распознавать формат российского госномера",
                        "маршрутизация запроса для номера уже заложена",
                        "можно подключать отдельный provider для поиска VIN по номеру",
                    ),
                ),
                ReportSection(
                    title="Что нужно следующим этапом",
                    lines=(
                        "выбрать законный и стабильный источник для номера автомобиля",
                        "реализовать преобразование госномер в VIN",
                        "после этого запускать обычную проверку автомобиля по VIN",
                    ),
                ),
            ),
        )
