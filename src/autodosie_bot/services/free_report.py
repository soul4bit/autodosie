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

_NOMEROGRAM_BASE_URL = "https://www.nomerogram.ru"
_NOMEROGRAM_REGION_URL = "https://www.nomerogram.ru/regions/{region}/{slug}/"
_NOMEROGRAM_SEARCH_URL = "https://www.nomerogram.ru/"
_NSIS_CHECK_URL = "https://nsis.ru/products/osago/check/"
_FNP_SEARCH_URL = "https://www.reestr-zalogov.ru/search/index"
_GIBDD_CHECK_URL = "https://xn--80aebkobnwfcnsfk1e0h.xn--p1ai/check/auto"
_NOMEROGRAM_PAGE_RE = re.compile(r'href="(https://www\.nomerogram\.ru/n/{slug}-[^"/]+/)"')
_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
_META_RE_TEMPLATE = r"<meta\s+{attr_name}=['\"]{attr_value}['\"]\s+content=['\"]([^'\"]+)['\"]"
_PHOTO_RE = re.compile(r"https://s\.nomerogram\.ru/photo/[^\s\"'>]+")
_VIN_MANUAL_LINKS = (
    "ГИБДД: /checkgibdd {vin}",
    f"Официальная страница ГИБДД: {_GIBDD_CHECK_URL}",
    f"Проверка ОСАГО НСИС: {_NSIS_CHECK_URL}",
    f"Реестр залогов ФНП: {_FNP_SEARCH_URL}",
)
_PLATE_MANUAL_LINKS = (
    f"Номерограм: {_NOMEROGRAM_SEARCH_URL}",
    f"Проверка ОСАГО НСИС: {_NSIS_CHECK_URL}",
    "Для полного официального отчета по ограничениям и розыску потребуется VIN.",
)


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
                    headers={"User-Agent": "autodosie-bot/0.1"},
                )
                region_response.raise_for_status()
                exact_page_url = self._extract_exact_page_url(region_response.text, slug)
                if not exact_page_url:
                    return None

                detail_response = await client.get(
                    exact_page_url,
                    headers={"User-Agent": "autodosie-bot/0.1"},
                )
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
        nhtsa_report = await self._nhtsa.check_vin(vin)
        sections = list(nhtsa_report.sections)
        sections.append(
            ReportSection(
                title="Бесплатные ручные проверки РФ",
                lines=tuple(line.format(vin=vin) for line in _VIN_MANUAL_LINKS),
            ),
        )

        summary = (
            "Бесплатный отчет собран автоматически из доступных открытых источников. "
            "Автоматически получены базовые данные по VIN; официальные российские проверки "
            "доступны по ссылкам ниже и частично требуют капчу или антибот-проверку."
        )

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
        nomerogram_result = await self._nomerogram.lookup_plate(normalized_plate)

        sections: list[ReportSection] = []
        summary = "Бесплатный отчет по госномеру собран из доступных открытых источников."

        if nomerogram_result is None:
            sections.append(
                ReportSection(
                    title="Номерограм",
                    lines=(
                        "Точная карточка номера в Номерограм не найдена.",
                        f"Поиск вручную: {_NOMEROGRAM_SEARCH_URL}",
                    ),
                ),
            )
            summary += " Публичные следы автомобиля по номеру не найдены, для полного отчета потребуется VIN."
        else:
            nomerogram_lines: list[str] = []
            if nomerogram_result.make_model:
                nomerogram_lines.append(f"Опознание: {nomerogram_result.make_model}")
            if nomerogram_result.title:
                nomerogram_lines.append(f"Заголовок карточки: {nomerogram_result.title}")
            if nomerogram_result.description:
                nomerogram_lines.append(f"Описание: {nomerogram_result.description}")
            nomerogram_lines.append(f"Карточка номера: {nomerogram_result.page_url}")
            nomerogram_lines.append(f"Найдено фото: {len(nomerogram_result.image_urls)}")
            nomerogram_lines.extend(
                f"Фото {index + 1}: {url}"
                for index, url in enumerate(nomerogram_result.image_urls[:3])
            )
            sections.append(ReportSection(title="Номерограм", lines=tuple(nomerogram_lines)))
            summary += (
                " Найдены публичные фото и карточка номера в Номерограм. "
                "Для официальных ограничений, розыска и регистрации все еще нужен VIN."
            )

        sections.append(
            ReportSection(
                title="Бесплатные ручные проверки",
                lines=_PLATE_MANUAL_LINKS,
            ),
        )

        return VehicleCheckReport(
            query_type="plate",
            query_value=normalized_plate,
            provider="free-aggregate",
            checked_at=datetime.now(tz=timezone.utc),
            summary=summary,
            sections=tuple(sections),
        )
