from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from urllib.parse import quote

import httpx

from autodosie_bot.services.base import ReportSection, VehicleCheckError, VehicleCheckReport
from autodosie_bot.services.nhtsa import NhtsaVehicleCheckService
from autodosie_bot.validation import normalize_plate

_NOMEROGRAM_REGION_URL = "https://www.nomerogram.ru/regions/{region}/{slug}/"
_NOMEROGRAM_SEARCH_URL = "https://www.nomerogram.ru/"
_NSIS_CHECK_URL = "https://nsis.ru/products/osago/check/"
_FNP_SEARCH_URL = "https://www.reestr-zalogov.ru/search/index"
_GIBDD_CHECK_URL = "https://xn--80aebkobnwfcnsfk1e0h.xn--p1ai/check/auto"
_NOMEROGRAM_PAGE_RE = re.compile(r'href="(https://www\.nomerogram\.ru/n/{slug}-[^"/]+/)"')
_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
_META_RE_TEMPLATE = r"<meta\s+{attr_name}=['\"]{attr_value}['\"]\s+content=['\"]([^'\"]+)['\"]"
_PHOTO_RE = re.compile(r"https://s\.nomerogram\.ru/photo/[^\s\"'>]+")
_VIN_SOURCE_STATUS_LINES = (
    "NHTSA vPIC: бесплатная базовая расшифровка VIN без истории владения и статусов по РФ.",
    "ГИБДД: официальный бесплатный источник по ограничениям, розыску, ДТП и техосмотру, но с капчей.",
    "НСИС: бесплатная проверка ОСАГО доступна через веб-форму.",
    "ФНП: бесплатный реестр залогов доступен без простого публичного JSON API.",
)
_PLATE_SOURCE_STATUS_LINES = (
    "Номерограм: помогает найти публичные карточки и фото по российскому номеру.",
    "НСИС: позволяет проверить наличие действующего ОСАГО.",
    "ГИБДД: для ограничений, розыска и регистраций по РФ понадобится VIN.",
)
_VIN_MANUAL_LINKS = (
    f"ГИБДД: официальный отчет по VIN — {_GIBDD_CHECK_URL}",
    f"НСИС: проверка ОСАГО — {_NSIS_CHECK_URL}",
    f"ФНП: реестр залогов — {_FNP_SEARCH_URL}",
)
_PLATE_MANUAL_LINKS = (
    f"Номерограм: ручной поиск по номеру — {_NOMEROGRAM_SEARCH_URL}",
    f"НСИС: проверка ОСАГО — {_NSIS_CHECK_URL}",
    f"ГИБДД: полный отчет по VIN — {_GIBDD_CHECK_URL}",
)
_PLATE_VIN_HINT_LINES = (
    "Надежного бесплатного автоматического способа получить VIN по госномеру без капчи и без серых баз сейчас нет.",
    "Публичная карточка Номерограм обычно помогает найти фото, объявления и модель автомобиля, но не раскрывает VIN в открытом HTML.",
    "Официальная проверка НСИС принимает госномер для проверки ОСАГО и может помочь вручную сверить автомобиль.",
    "Если VIN нужен для полноценной проверки ГИБДД, практичный путь — запросить у продавца фото СТС, ПТС или таблички VIN.",
)
_USER_AGENT = "autodosie-web/0.1"


@dataclass(frozen=True, slots=True)
class NomerogramResult:
    page_url: str
    title: str
    description: str
    make_model: str
    image_urls: tuple[str, ...]


class NomerogramLookupService:
    def __init__(self, timeout_seconds: float) -> None:
        self._timeout = timeout_seconds

    async def lookup_plate(self, plate: str) -> NomerogramResult | None:
        normalized_plate = normalize_plate(plate)
        region = normalized_plate[-3:] if normalized_plate[-3:].isdigit() else normalized_plate[-2:]
        slug = normalized_plate.lower()
        region_url = _NOMEROGRAM_REGION_URL.format(region=quote(region), slug=quote(slug))

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                region_response = await client.get(
                    region_url,
                    headers={"User-Agent": _USER_AGENT},
                )
                if region_response.status_code == 404:
                    return None
                region_response.raise_for_status()
                exact_page_url = self._extract_exact_page_url(region_response.text, slug)
                if not exact_page_url:
                    return None

                detail_response = await client.get(
                    exact_page_url,
                    headers={"User-Agent": _USER_AGENT},
                )
                if detail_response.status_code == 404:
                    return None
                detail_response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise VehicleCheckError("Номерограм отвечает слишком долго. Повтори запрос позже.") from exc
        except httpx.HTTPError as exc:
            raise VehicleCheckError("Не удалось получить ответ от Номерограм.") from exc

        title = self._extract_meta(detail_response.text, _TITLE_RE)
        description = self._extract_meta(
            detail_response.text,
            re.compile(_META_RE_TEMPLATE.format(attr_name="name", attr_value="description"), re.IGNORECASE),
        )
        if not description:
            description = self._extract_meta(
                detail_response.text,
                re.compile(
                    _META_RE_TEMPLATE.format(attr_name="property", attr_value="og:description"),
                    re.IGNORECASE,
                ),
            )
        images = self._extract_images(detail_response.text)

        return NomerogramResult(
            page_url=exact_page_url,
            title=title,
            description=description,
            make_model=self._extract_make_model(title, normalized_plate),
            image_urls=images,
        )

    def _extract_exact_page_url(self, region_html: str, slug: str) -> str:
        match = re.search(
            _NOMEROGRAM_PAGE_RE.pattern.format(slug=re.escape(slug)),
            region_html,
            re.IGNORECASE,
        )
        if not match:
            return ""
        return unescape(match.group(1))

    def _extract_meta(self, html: str, pattern: re.Pattern[str]) -> str:
        match = pattern.search(html)
        if not match:
            return ""
        return unescape(match.group(1)).strip()

    def _extract_images(self, html: str) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []

        for raw_url in _PHOTO_RE.findall(html):
            image_url = raw_url.strip()
            if image_url.endswith(" 2x"):
                image_url = image_url[:-3].rstrip()
            if image_url in seen:
                continue
            seen.add(image_url)
            ordered.append(image_url)

        return tuple(ordered)

    def _extract_make_model(self, title: str, plate: str) -> str:
        if not title:
            return ""

        normalized_title = title.replace("История авто ", "", 1)
        marker = f" с гос. номером {plate}"
        if marker in normalized_title:
            return normalized_title.split(marker, 1)[0].strip()
        return ""


class FreeVehicleCheckService:
    def __init__(self, timeout_seconds: float) -> None:
        self._nhtsa = NhtsaVehicleCheckService(timeout_seconds=timeout_seconds)
        self._nomerogram = NomerogramLookupService(timeout_seconds=timeout_seconds)

    async def check_vin(self, vin: str) -> VehicleCheckReport:
        sections: list[ReportSection] = []

        try:
            nhtsa_report = await self._nhtsa.check_vin(vin)
        except VehicleCheckError as exc:
            sections.append(
                ReportSection(
                    title="Автоматическая расшифровка VIN",
                    lines=(
                        f"NHTSA vPIC временно недоступен: {exc}",
                        "Ниже остаются бесплатные российские проверки, которые можно открыть вручную.",
                    ),
                ),
            )
            summary = (
                "Бесплатный отчет по VIN собран частично: автоматическая расшифровка VIN сейчас недоступна. "
                "Для полной картины по РФ открой ГИБДД, НСИС и реестр залогов."
            )
        else:
            sections.extend(self._drop_source_sections(nhtsa_report.sections))
            summary = (
                f"{nhtsa_report.summary} "
                "Дополнительно отчет подсказывает бесплатные российские проверки по ограничениям, ОСАГО и залогам."
            )

        sections.append(ReportSection(title="Бесплатные источники РФ", lines=_VIN_SOURCE_STATUS_LINES))
        sections.append(ReportSection(title="Что проверить вручную", lines=_VIN_MANUAL_LINKS))

        return VehicleCheckReport(
            query_type="vin",
            query_value=vin,
            provider="free-aggregate",
            checked_at=datetime.now(tz=timezone.utc),
            summary=summary,
            sections=tuple(sections),
        )

    async def check_plate(self, plate: str) -> VehicleCheckReport:
        normalized_plate = normalize_plate(plate)
        sections: list[ReportSection] = []

        try:
            nomerogram_result = await self._nomerogram.lookup_plate(normalized_plate)
        except VehicleCheckError as exc:
            nomerogram_result = None
            sections.append(
                ReportSection(
                    title="Публичные следы по номеру",
                    lines=(
                        f"Номерограм временно недоступен: {exc}",
                        f"Ручной поиск: {_NOMEROGRAM_SEARCH_URL}",
                    ),
                ),
            )
            summary = (
                "Бесплатный отчет по госномеру собран частично: источник публичных следов сейчас недоступен. "
                "Для официальных ограничений, розыска и регистраций дальше понадобится VIN."
            )
        else:
            if nomerogram_result is None:
                sections.append(
                    ReportSection(
                        title="Публичные следы по номеру",
                        lines=(
                            "Точная карточка номера в Номерограм не найдена.",
                            f"Ручной поиск: {_NOMEROGRAM_SEARCH_URL}",
                        ),
                    ),
                )
                summary = (
                    "Бесплатный отчет по госномеру не нашел публичных следов автомобиля. "
                    "Для официальных ограничений, розыска и регистраций дальше понадобится VIN."
                )
            else:
                sections.append(self._build_nomerogram_section(nomerogram_result))
                summary = (
                    "Бесплатный отчет по госномеру собран из открытых источников. "
                    "Найдены публичные следы автомобиля по номеру, а для официальной проверки следующий шаг — VIN."
                )

        sections.append(ReportSection(title="Бесплатные источники", lines=_PLATE_SOURCE_STATUS_LINES))
        sections.append(ReportSection(title="Как попробовать найти VIN", lines=_PLATE_VIN_HINT_LINES))
        sections.append(ReportSection(title="Что проверить вручную", lines=_PLATE_MANUAL_LINKS))

        return VehicleCheckReport(
            query_type="plate",
            query_value=normalized_plate,
            provider="free-aggregate",
            checked_at=datetime.now(tz=timezone.utc),
            summary=summary,
            sections=tuple(sections),
        )

    def _build_nomerogram_section(self, result: NomerogramResult) -> ReportSection:
        lines: list[str] = []
        if result.make_model:
            lines.append(f"Опознание: {result.make_model}")
        if result.title:
            lines.append(f"Заголовок карточки: {result.title}")
        if result.description:
            lines.append(f"Описание: {result.description}")
        lines.append(f"Карточка номера: {result.page_url}")
        lines.append(f"Найдено фото: {len(result.image_urls)}")
        lines.extend(
            f"Фото {index + 1}: {url}"
            for index, url in enumerate(result.image_urls[:3])
        )
        return ReportSection(title="Публичные следы по номеру", lines=tuple(lines))

    def _drop_source_sections(self, sections: tuple[ReportSection, ...]) -> list[ReportSection]:
        return [section for section in sections if section.title != "Источник данных"]
