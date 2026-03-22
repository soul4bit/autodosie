from __future__ import annotations

from datetime import datetime, timezone

from autodosie_bot.services.base import ReportSection, VehicleCheckReport


class StubVehicleCheckService:
    async def check_vin(self, vin: str) -> VehicleCheckReport:
        return VehicleCheckReport(
            vin=vin,
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
