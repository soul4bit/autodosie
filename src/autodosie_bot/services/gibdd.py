from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from autodosie_bot.services.base import ReportSection, VehicleCheckError, VehicleCheckReport

_GIBDD_REFERER = "https://xn--80aebkobnwfcnsfk1e0h.xn--p1ai/check/auto"
_GIBDD_ORIGIN = "https://xn--80aebkobnwfcnsfk1e0h.xn--p1ai"
_GIBDD_CAPTCHA_URL = "https://check.gibdd.ru/captcha"
_GIBDD_REGISTER_URL = "https://check.gibdd.ru/proxy/check/auto/register"
_GIBDD_WANTED_URL = "https://check.gibdd.ru/proxy/check/auto/wanted"
_GIBDD_RESTRICT_URL = "https://check.gibdd.ru/proxy/check/auto/restrict"
_GIBDD_DIAGNOSTIC_URL = "https://check.gibdd.ru/proxy/check/auto/diagnostic"
_GIBDD_DTP_URL = "https://check.gibdd.ru/proxy/check/auto/dtp"
_GIBDD_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
_CAPTCHA_ERROR_TEXT = "Капча введена неверно или устарела."
_GIBDD_STOP_TEXT = "Сервис ГИБДД временно недоступен. Повтори проверку позже."
_GIBDD_FAIL_TEXT = "Сервис ГИБДД вернул неожиданный ответ."
_GIBDD_SESSION_TEXT = "Сессия проверки ГИБДД устарела. Начни проверку заново."
_OWNER_TYPE_LABELS = {
    "natural": "Физическое лицо",
    "legal": "Юридическое лицо",
}
_RESTRICTION_DIVISION_LABELS = {
    "0": "Не предусмотренный код",
    "1": "Судебные органы",
    "2": "Судебный пристав",
    "3": "Таможенные органы",
    "4": "Органы социальной защиты",
    "5": "Нотариус",
    "6": "ОВД или иные правоохранительные органы",
    "7": "ОВД или иные правоохранительные органы (прочие)",
}
_RESTRICTION_KIND_LABELS = {
    "1": "Запрет на регистрационные действия",
    "2": "Запрет на снятие с учета",
    "3": "Запрет на регистрационные действия и прохождение ГТО",
    "4": "Утилизация",
    "5": "Аннулирование",
}
_CHECK_LABELS = {
    "history": "история регистраций",
    "wanted": "розыск",
    "restricted": "ограничения",
    "diagnostic": "техосмотр",
    "aiusdtp": "ДТП",
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GibddCaptchaChallenge:
    vin: str
    captcha_token: str
    image_bytes: bytes
    cookies: dict[str, str]


@dataclass(frozen=True, slots=True)
class _EndpointResult:
    kind: Literal["ok", "empty", "error"]
    message: str
    payload: dict[str, Any] | None = None


class GibddCaptchaError(VehicleCheckError):
    """Raised when GIBDD rejects or expires the captcha."""


class GibddCheckService:
    def __init__(
        self,
        timeout_seconds: float,
        captcha_wait_seconds: float,
        captcha_poll_interval_seconds: float,
    ) -> None:
        self._timeout = timeout_seconds
        self._captcha_wait_seconds = max(captcha_wait_seconds, 0.0)
        self._captcha_poll_interval_seconds = max(captcha_poll_interval_seconds, 1.0)

    @property
    def captcha_wait_seconds(self) -> float:
        return self._captcha_wait_seconds

    async def begin_vin_check(self, vin: str) -> GibddCaptchaChallenge:
        last_error: Exception | None = None
        deadline = time.monotonic() + self._captcha_wait_seconds
        attempt = 0

        while True:
            attempt += 1
            try:
                async with self._build_client() as client:
                    response = await client.get(_GIBDD_CAPTCHA_URL)
                    response.raise_for_status()
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning("GIBDD captcha timeout on attempt %s", attempt)
                if time.monotonic() < deadline:
                    await asyncio.sleep(self._captcha_poll_interval_seconds)
                    continue
                raise VehicleCheckError(
                    "ГИБДД не выдал капчу за отведенное время. Возможно, сервис недоступен или с этого VPS к нему плохой доступ.",
                ) from exc
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                logger.warning("GIBDD captcha returned HTTP %s on attempt %s", status_code, attempt)
                if status_code in {502, 503, 504} and time.monotonic() < deadline:
                    await asyncio.sleep(self._captcha_poll_interval_seconds)
                    continue
                raise VehicleCheckError(self._describe_captcha_http_error(status_code)) from exc
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("GIBDD captcha request failed on attempt %s: %s", attempt, exc)
                if time.monotonic() < deadline:
                    await asyncio.sleep(self._captcha_poll_interval_seconds)
                    continue
                raise VehicleCheckError("Не удалось подключиться к сервису капчи ГИБДД.") from exc

            break

        if last_error is not None and response is None:
            raise VehicleCheckError("Не удалось получить капчу ГИБДД.") from last_error

        try:
            payload = response.json()
            captcha_token = str(payload["token"]).strip()
            image_base64 = str(payload["base64jpg"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise VehicleCheckError("ГИБДД вернул некорректный ответ при запросе капчи.") from exc

        if not captcha_token or not image_base64:
            raise VehicleCheckError("ГИБДД не прислал данные капчи.")

        try:
            image_bytes = base64.b64decode(image_base64)
        except ValueError as exc:
            raise VehicleCheckError("Не удалось декодировать изображение капчи ГИБДД.") from exc

        return GibddCaptchaChallenge(
            vin=vin,
            captcha_token=captcha_token,
            image_bytes=image_bytes,
            cookies={name: value for name, value in client.cookies.items()},
        )

    async def check_vin(
        self,
        vin: str,
        captcha_word: str,
        captcha_token: str,
        cookies: dict[str, str],
    ) -> VehicleCheckReport:
        try:
            async with self._build_client() as client:
                client.cookies.update(cookies)
                results = {
                    "history": await self._run_endpoint(
                        client=client,
                        url=_GIBDD_REGISTER_URL,
                        check_type="history",
                        vin=vin,
                        captcha_word=captcha_word,
                        captcha_token=captcha_token,
                    ),
                    "wanted": await self._run_endpoint(
                        client=client,
                        url=_GIBDD_WANTED_URL,
                        check_type="wanted",
                        vin=vin,
                        captcha_word=captcha_word,
                        captcha_token=captcha_token,
                    ),
                    "restricted": await self._run_endpoint(
                        client=client,
                        url=_GIBDD_RESTRICT_URL,
                        check_type="restricted",
                        vin=vin,
                        captcha_word=captcha_word,
                        captcha_token=captcha_token,
                    ),
                    "diagnostic": await self._run_endpoint(
                        client=client,
                        url=_GIBDD_DIAGNOSTIC_URL,
                        check_type="diagnostic",
                        vin=vin,
                        captcha_word=captcha_word,
                        captcha_token=captcha_token,
                    ),
                    "aiusdtp": await self._run_endpoint(
                        client=client,
                        url=_GIBDD_DTP_URL,
                        check_type="aiusdtp",
                        vin=vin,
                        captcha_word=captcha_word,
                        captcha_token=captcha_token,
                    ),
                }
        except httpx.TimeoutException as exc:
            raise VehicleCheckError("ГИБДД отвечает слишком долго. Повтори запрос позже.") from exc
        except httpx.HTTPError as exc:
            raise VehicleCheckError("Не удалось получить ответ от ГИБДД.") from exc

        if all(result.kind == "error" for result in results.values()):
            first_error = next(result.message for result in results.values() if result.message)
            raise VehicleCheckError(first_error or "Не удалось выполнить проверку через ГИБДД.")

        return self._build_report(vin=vin, results=results)

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control": "no-cache",
                "Origin": _GIBDD_ORIGIN,
                "Pragma": "no-cache",
                "Referer": _GIBDD_REFERER,
                "User-Agent": _GIBDD_USER_AGENT,
                "X-Requested-With": "XMLHttpRequest",
            },
        )

    async def _run_endpoint(
        self,
        client: httpx.AsyncClient,
        url: str,
        check_type: str,
        vin: str,
        captcha_word: str,
        captcha_token: str,
    ) -> _EndpointResult:
        response = await client.post(
            url,
            data={
                "vin": vin,
                "checkType": check_type,
                "captchaWord": captcha_word,
                "captchaToken": captcha_token,
            },
        )
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError:
            return _EndpointResult(kind="error", message=_GIBDD_FAIL_TEXT)

        if not isinstance(payload, dict):
            return _EndpointResult(kind="error", message=_GIBDD_FAIL_TEXT)

        status = payload.get("status")
        code = payload.get("code")
        message = self._clean_text(payload.get("message"))

        if code == 201 or status == 201:
            raise GibddCaptchaError(message or _CAPTCHA_ERROR_TEXT)

        if status == 403 and "vin" not in payload:
            raise VehicleCheckError(_GIBDD_SESSION_TEXT)

        if status == 200 and isinstance(payload.get("RequestResult"), dict):
            return _EndpointResult(kind="ok", message="", payload=payload)

        if check_type == "history" and status == 403:
            return _EndpointResult(
                kind="empty",
                message=message or "Информация по указанному VIN не может быть предоставлена.",
            )

        if check_type == "history" and status == 404:
            return _EndpointResult(
                kind="empty",
                message=message or "По указанному VIN не найдена информация о регистрации транспортного средства.",
            )

        if status == 503:
            return _EndpointResult(kind="error", message=_GIBDD_STOP_TEXT)

        if message:
            return _EndpointResult(kind="error", message=message)

        return _EndpointResult(kind="error", message=_GIBDD_FAIL_TEXT)

    def _describe_captcha_http_error(self, status_code: int) -> str:
        if status_code == 403:
            return "ГИБДД отклоняет запрос к капче с этого сервера: HTTP 403. Вероятно, IP VPS блокируется."
        if status_code == 429:
            return "ГИБДД ограничил выдачу капчи: HTTP 429. Попробуй позже."
        if status_code == 503:
            return (
                "ГИБДД сейчас отдает HTTP 503 при выдаче капчи. "
                f"Бот ждал ее до {int(self._captcha_wait_seconds)} сек, но сервис так и не ответил нормально."
            )
        if status_code in {502, 504}:
            return f"ГИБДД сейчас недоступен при выдаче капчи: HTTP {status_code}."
        return f"ГИБДД не выдал капчу: HTTP {status_code}."

    def _build_report(
        self,
        vin: str,
        results: dict[str, _EndpointResult],
    ) -> VehicleCheckReport:
        sections: list[ReportSection] = []
        summary_parts: list[str] = []
        error_lines: list[str] = []

        overview_section = self._build_overview_section(results)
        sections.append(overview_section)

        history = results["history"]
        history_payload = history.payload["RequestResult"] if history.payload else {}
        history_sections, history_summary = self._build_history_sections(history)
        sections.extend(history_sections)
        if history_summary:
            summary_parts.append(history_summary)

        wanted_sections, wanted_summary = self._build_wanted_section(results["wanted"])
        sections.extend(wanted_sections)
        if wanted_summary:
            summary_parts.append(wanted_summary)

        restricted_sections, restricted_summary = self._build_restrictions_section(results["restricted"])
        sections.extend(restricted_sections)
        if restricted_summary:
            summary_parts.append(restricted_summary)

        diagnostic_sections, diagnostic_summary = self._build_diagnostic_section(results["diagnostic"])
        sections.extend(diagnostic_sections)
        if diagnostic_summary:
            summary_parts.append(diagnostic_summary)

        accident_sections, accident_summary = self._build_accidents_section(results["aiusdtp"])
        sections.extend(accident_sections)
        if accident_summary:
            summary_parts.append(accident_summary)

        for name, result in results.items():
            if result.kind == "error":
                error_lines.append(f"{_CHECK_LABELS[name].capitalize()}: {result.message}")

        if error_lines:
            sections.append(ReportSection(title="Проблемы при проверке", lines=tuple(error_lines)))

        vehicle_title = self._join_non_empty(
            history_payload.get("vehicle_brandmodel"),
            history_payload.get("vehicle_releaseyear"),
        )
        if vehicle_title:
            summary_prefix = f"Официальная проверка ГИБДД по {vehicle_title}"
        else:
            summary_prefix = "Официальная проверка ГИБДД"

        summary = summary_prefix
        if summary_parts:
            summary += ": " + ", ".join(summary_parts) + "."
        else:
            summary += " завершена."

        if error_lines:
            summary += " Часть разделов вернула ошибку."

        if not sections:
            sections.append(
                ReportSection(
                    title="Результат",
                    lines=("ГИБДД не вернуло ни одного распознаваемого блока данных.",),
                ),
            )

        return VehicleCheckReport(
            query_type="vin",
            query_value=vin,
            provider="gibdd-official",
            checked_at=datetime.now(tz=timezone.utc),
            summary=summary,
            sections=tuple(sections),
        )

    def _build_overview_section(self, results: dict[str, _EndpointResult]) -> ReportSection:
        lines = (
            self._summarize_history_status(results["history"]),
            self._summarize_wanted_status(results["wanted"]),
            self._summarize_restrictions_status(results["restricted"]),
            self._summarize_diagnostic_status(results["diagnostic"]),
            self._summarize_accidents_status(results["aiusdtp"]),
        )
        return ReportSection(title="Сводка по ГИБДД", lines=lines)

    def _build_history_sections(self, result: _EndpointResult) -> tuple[list[ReportSection], str]:
        if result.kind == "empty":
            return [ReportSection(title="История регистрации", lines=(result.message,))], "история регистрации: нет данных"

        if result.kind == "error" or not result.payload:
            return [], ""

        obj = result.payload["RequestResult"]
        main_lines = self._collect_lines(
            (
                ("Статус реестра", obj.get("reestr_status")),
                ("Модель", obj.get("vehicle_brandmodel")),
                ("VIN", obj.get("vehicle_vin")),
                ("Кузов", obj.get("vehicle_body_number")),
                ("Шасси", obj.get("chassisNumber")),
                ("Цвет", obj.get("vehicle_bodycolor")),
                (
                    "Мощность",
                    self._join_non_empty(
                        self._clean_text(obj.get("vehicle_enginepowerkw")),
                        self._clean_text(obj.get("vehicle_enginepower")),
                        separator=" кВт / ",
                    ),
                ),
                ("Год выпуска", obj.get("vehicle_releaseyear")),
                ("Объем двигателя", obj.get("vehicle_enclosedvolume")),
                ("Экокласс", obj.get("vehicle_eco_class")),
                ("Тип ТС", obj.get("vehicle_type_name")),
            ),
        )

        sections: list[ReportSection] = []
        if main_lines:
            sections.append(ReportSection(title="История регистрации", lines=tuple(main_lines)))

        periods = self._as_list(obj.get("periods"))
        period_lines: list[str] = []
        for period in periods:
            if not isinstance(period, dict):
                continue

            date_from = self._clean_text(period.get("startDate")) or "нет данных"
            date_to = self._clean_text(period.get("endDate")) or "настоящее время"
            owner_type = self._describe_owner_type(period.get("ownerType"))
            period_lines.append(f"{date_from} -> {date_to}: {owner_type}")

        if period_lines:
            sections.append(ReportSection(title="Периоды владения", lines=tuple(period_lines)))

        return sections, f"периодов владения: {len(period_lines)}"

    def _build_wanted_section(self, result: _EndpointResult) -> tuple[list[ReportSection], str]:
        if result.kind == "error" or not result.payload:
            return [], ""

        records = self._as_list(result.payload["RequestResult"].get("records"))
        if not records:
            return [
                ReportSection(title="Розыск", lines=("По данным ГИБДД автомобиль в розыске не числится.",)),
            ], "розыск: нет"

        lines: list[str] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            model = self._join_non_empty(record.get("w_model"), record.get("w_god_vyp"))
            description = self._join_non_empty(
                model,
                self._label("Дата розыска", record.get("w_data_pu")),
                self._label("Госномер", record.get("w_reg_zn")),
                self._label("Инициатор", record.get("w_reg_inic")),
                separator="; ",
            )
            if description:
                lines.append(description)

        if not lines:
            lines.append("ГИБДД вернуло блок розыска без детализированных записей.")

        return [ReportSection(title="Розыск", lines=tuple(lines))], f"розыск: {len(lines)} запись(ей)"

    def _build_restrictions_section(self, result: _EndpointResult) -> tuple[list[ReportSection], str]:
        if result.kind == "error" or not result.payload:
            return [], ""

        records = self._as_list(result.payload["RequestResult"].get("records"))
        if not records:
            return [
                ReportSection(
                    title="Ограничения",
                    lines=("По данным ГИБДД ограничений на регистрационные действия не найдено.",),
                ),
            ], "ограничения: нет"

        lines: list[str] = []
        for record in records:
            if not isinstance(record, dict):
                continue

            description = self._join_non_empty(
                self._join_non_empty(record.get("tsmodel"), record.get("tsyear")),
                self._label("Дата", record.get("dateogr")),
                self._label("Регион", record.get("regname")),
                self._label("Орган", _RESTRICTION_DIVISION_LABELS.get(self._clean_text(record.get("divtype")))),
                self._label("Ограничение", _RESTRICTION_KIND_LABELS.get(self._clean_text(record.get("ogrkod")))),
                self._label("Основание", record.get("osnOgr")),
                self._label("Телефон", record.get("phone")),
                self._label("ГИД", record.get("gid")),
                separator="; ",
            )
            if description:
                lines.append(description)

        if not lines:
            lines.append("ГИБДД вернуло блок ограничений без детализированных записей.")

        return [ReportSection(title="Ограничения", lines=tuple(lines))], f"ограничения: {len(lines)} запись(ей)"

    def _build_diagnostic_section(self, result: _EndpointResult) -> tuple[list[ReportSection], str]:
        if result.kind == "error" or not result.payload:
            return [], ""

        cards = self._as_list(result.payload["RequestResult"].get("diagnosticCards"))
        if not cards:
            return [
                ReportSection(
                    title="Техосмотр",
                    lines=("По данным ГИБДД диагностические карты не найдены.",),
                ),
            ], "техосмотр: нет"

        lines: list[str] = []
        for card in cards:
            if not isinstance(card, dict):
                continue

            description = self._join_non_empty(
                self._label("Карта", card.get("dcNumber")),
                self._label("Дата", self._normalize_date(card.get("dcDate"))),
                self._label("Действует до", self._normalize_date(card.get("dcExpirationDate"))),
                self._label("Оператор", card.get("operatorName")),
                self._label("Пункт", card.get("pointAddress")),
                self._label(
                    "Авто",
                    self._join_non_empty(card.get("brand"), card.get("model")),
                ),
                self._label("Пробег", card.get("odometerValue")),
                separator="; ",
            )
            if description:
                lines.append(description)

        if not lines:
            lines.append("ГИБДД вернуло блок техосмотра без детализированных записей.")

        return [ReportSection(title="Техосмотр", lines=tuple(lines))], f"техосмотр: {len(lines)} карта(ы)"

    def _build_accidents_section(self, result: _EndpointResult) -> tuple[list[ReportSection], str]:
        if result.kind == "error" or not result.payload:
            return [], ""

        accidents = self._as_list(result.payload["RequestResult"].get("Accidents"))
        if not accidents:
            return [
                ReportSection(
                    title="ДТП",
                    lines=("По данным ГИБДД записи о ДТП не найдены.",),
                ),
            ], "ДТП: нет"

        lines: list[str] = []
        for accident in accidents:
            if not isinstance(accident, dict):
                continue

            description = self._join_non_empty(
                self._label("Дата", accident.get("AccidentDateTime")),
                self._label("№", accident.get("AccidentNumber")),
                self._label("Тип", accident.get("AccidentType")),
                self._label("Регион", accident.get("RegionName")),
                self._label("Место", accident.get("AccidentPlace")),
                self._label("Подразделение", accident.get("DepName")),
                self._label("ТС", self._join_non_empty(accident.get("VehicleMark"), accident.get("VehicleModel"))),
                self._label("Участников", accident.get("VehicleAmount")),
                self._label("Повреждения", self._truncate(accident.get("DamageDestription"))),
                separator="; ",
            )
            if description:
                lines.append(description)

        if not lines:
            lines.append("ГИБДД вернуло блок ДТП без детализированных записей.")

        return [ReportSection(title="ДТП", lines=tuple(lines))], f"ДТП: {len(lines)} запись(ей)"

    def _summarize_history_status(self, result: _EndpointResult) -> str:
        if result.kind == "error":
            return f"История регистрации: не удалось получить ({result.message})"
        if result.kind == "empty" or not result.payload:
            return "История регистрации: данных не найдено"

        payload = result.payload["RequestResult"]
        periods = self._as_list(payload.get("periods"))
        vehicle_title = self._join_non_empty(payload.get("vehicle_brandmodel"), payload.get("vehicle_releaseyear"))
        if vehicle_title and periods:
            return f"История регистрации: {vehicle_title}, периодов владения: {len(periods)}"
        if periods:
            return f"История регистрации: найдено периодов владения: {len(periods)}"
        if vehicle_title:
            return f"История регистрации: найдена карточка ТС ({vehicle_title})"
        return "История регистрации: сведения получены"

    def _summarize_wanted_status(self, result: _EndpointResult) -> str:
        if result.kind == "error":
            return f"Розыск: не удалось получить ({result.message})"
        if not result.payload:
            return "Розыск: данных нет"

        records = self._as_list(result.payload["RequestResult"].get("records"))
        if not records:
            return "Розыск: автомобиль не числится"
        return f"Розыск: найдено записей: {len(records)}"

    def _summarize_restrictions_status(self, result: _EndpointResult) -> str:
        if result.kind == "error":
            return f"Ограничения: не удалось получить ({result.message})"
        if not result.payload:
            return "Ограничения: данных нет"

        records = self._as_list(result.payload["RequestResult"].get("records"))
        if not records:
            return "Ограничения: не найдены"
        return f"Ограничения: найдено записей: {len(records)}"

    def _summarize_diagnostic_status(self, result: _EndpointResult) -> str:
        if result.kind == "error":
            return f"Техосмотр: не удалось получить ({result.message})"
        if not result.payload:
            return "Техосмотр: данных нет"

        cards = self._as_list(result.payload["RequestResult"].get("diagnosticCards"))
        if not cards:
            return "Техосмотр: диагностические карты не найдены"
        return f"Техосмотр: найдено карт: {len(cards)}"

    def _summarize_accidents_status(self, result: _EndpointResult) -> str:
        if result.kind == "error":
            return f"ДТП: не удалось получить ({result.message})"
        if not result.payload:
            return "ДТП: данных нет"

        accidents = self._as_list(result.payload["RequestResult"].get("Accidents"))
        if not accidents:
            return "ДТП: записей не найдено"
        return f"ДТП: найдено записей: {len(accidents)}"

    def _collect_lines(self, pairs: tuple[tuple[str, Any], ...]) -> list[str]:
        lines: list[str] = []
        for label, value in pairs:
            cleaned = self._clean_text(value)
            if cleaned:
                lines.append(f"{label}: {cleaned}")
        return lines

    def _describe_owner_type(self, value: Any) -> str:
        cleaned = self._clean_text(value)
        if not cleaned:
            return "тип владельца не указан"
        return _OWNER_TYPE_LABELS.get(cleaned.lower(), cleaned)

    def _as_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _normalize_date(self, value: Any) -> str:
        cleaned = self._clean_text(value)
        if len(cleaned) == 10 and cleaned[4] == "-" and cleaned[7] == "-":
            year, month, day = cleaned.split("-")
            return f"{day}.{month}.{year}"
        return cleaned

    def _label(self, label: str, value: Any) -> str:
        cleaned = self._clean_text(value)
        if not cleaned:
            return ""
        return f"{label}: {cleaned}"

    def _join_non_empty(self, *parts: Any, separator: str = " ") -> str:
        cleaned_parts = [self._clean_text(part) for part in parts]
        return separator.join(part for part in cleaned_parts if part)

    def _truncate(self, value: Any, limit: int = 180) -> str:
        cleaned = self._clean_text(value)
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 1].rstrip() + "..."

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        cleaned = str(value).strip()
        if cleaned in {"", "null", "None", "undefined"}:
            return ""
        return cleaned
