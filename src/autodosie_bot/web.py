from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from autodosie_bot.config import AppConfig, load_config
from autodosie_bot.logging_config import configure_logging
from autodosie_bot.query import VehicleQuery, parse_vehicle_query
from autodosie_bot.services.base import VehicleCheckError, VehicleCheckReport, VehicleCheckService
from autodosie_bot.services.factory import build_vehicle_check_service
from autodosie_bot.services.gibdd import GibddCaptchaChallenge, GibddCaptchaError, GibddCheckService

_PACKAGE_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _PACKAGE_DIR / "templates"
_STATIC_DIR = _PACKAGE_DIR / "static"
_EXAMPLE_VIN = "XTA210740Y1234567"
_EXAMPLE_PLATE = "A123BC77"
_GIBDD_CHALLENGE_TTL_SECONDS = 300.0
_GIBDD_DIRECTION_LABELS = (
    "История регистрации",
    "Розыск",
    "Ограничения на регистрационные действия",
    "Техосмотр",
    "ДТП",
)


@dataclass(slots=True)
class _StoredGibddChallenge:
    challenge: GibddCaptchaChallenge
    created_at: float


class _GibddChallengeStore:
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = max(ttl_seconds, 60.0)
        self._items: dict[str, _StoredGibddChallenge] = {}

    def put(self, challenge: GibddCaptchaChallenge) -> str:
        self._purge()
        challenge_id = uuid4().hex
        self._items[challenge_id] = _StoredGibddChallenge(
            challenge=challenge,
            created_at=time.monotonic(),
        )
        return challenge_id

    def get(self, challenge_id: str) -> GibddCaptchaChallenge | None:
        self._purge()
        stored = self._items.get(challenge_id)
        if stored is None:
            return None
        return stored.challenge

    def pop(self, challenge_id: str) -> GibddCaptchaChallenge | None:
        self._purge()
        stored = self._items.pop(challenge_id, None)
        if stored is None:
            return None
        return stored.challenge

    def _purge(self) -> None:
        now = time.monotonic()
        expired_ids = [
            challenge_id
            for challenge_id, stored in self._items.items()
            if now - stored.created_at > self._ttl_seconds
        ]
        for challenge_id in expired_ids:
            self._items.pop(challenge_id, None)


def build_app() -> FastAPI:
    config = load_config()
    configure_logging(config.log_level)
    vehicle_check_service = build_vehicle_check_service(config)
    gibdd_check_service = GibddCheckService(
        timeout_seconds=config.request_timeout_seconds,
        captcha_wait_seconds=config.gibdd_captcha_wait_seconds,
        captcha_poll_interval_seconds=config.gibdd_captcha_poll_interval_seconds,
    )
    gibdd_challenges = _GibddChallengeStore(ttl_seconds=_GIBDD_CHALLENGE_TTL_SECONDS)

    app = FastAPI(
        title=config.site_name,
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    app.state.config = config
    app.state.templates = templates
    app.state.vehicle_check_service = vehicle_check_service
    app.state.gibdd_check_service = gibdd_check_service
    app.state.gibdd_challenges = gibdd_challenges
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=_base_context(
                config=config,
                active_page="home",
                request=request,
                submitted_query="",
                error_message="",
            ),
        )

    @app.get("/sources", response_class=HTMLResponse)
    async def sources_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="sources.html",
            context=_base_context(
                config=config,
                active_page="sources",
                request=request,
                submitted_query="",
                error_message="",
            ),
        )

    @app.get("/report", response_class=HTMLResponse)
    async def report_page(request: Request, q: str = "") -> HTMLResponse:
        query = parse_vehicle_query(q)
        if query is None:
            return _render_invalid_query_response(
                config=config,
                request=request,
                templates=templates,
                submitted_query=q,
                error_message=(
                    "Нужен VIN из 17 символов или российский госномер в формате A123BC77 либо A123BC777."
                ),
            )

        try:
            report = await _run_vehicle_report(vehicle_check_service, query)
        except VehicleCheckError as exc:
            return templates.TemplateResponse(
                request=request,
                name="report.html",
                context=_report_context(
                    config=config,
                    request=request,
                    query=query,
                    report=None,
                    error_message=str(exc),
                ),
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        return templates.TemplateResponse(
            request=request,
            name="report.html",
            context=_report_context(
                config=config,
                request=request,
                query=query,
                report=report,
                error_message="",
            ),
        )

    @app.get("/report/gibdd", response_class=HTMLResponse)
    async def gibdd_captcha_page(request: Request, q: str = "") -> HTMLResponse:
        query = parse_vehicle_query(q)
        if query is None or query.kind != "vin":
            return _render_invalid_query_response(
                config=config,
                request=request,
                templates=templates,
                submitted_query=q,
                error_message="Для официальной проверки ГИБДД нужен VIN из 17 символов.",
            )

        return await _start_gibdd_captcha_flow(
            config=config,
            request=request,
            templates=templates,
            gibdd_check_service=gibdd_check_service,
            gibdd_challenges=gibdd_challenges,
            query=query,
            error_message="",
            status_code=status.HTTP_200_OK,
        )

    @app.post("/report/gibdd", response_class=HTMLResponse)
    async def gibdd_report_page(
        request: Request,
        q: str = Form(""),
        challenge_id: str = Form(""),
        captcha_word: str = Form(""),
    ) -> HTMLResponse:
        query = parse_vehicle_query(q)
        if query is None or query.kind != "vin":
            return _render_invalid_query_response(
                config=config,
                request=request,
                templates=templates,
                submitted_query=q,
                error_message="Для официальной проверки ГИБДД нужен VIN из 17 символов.",
            )

        normalized_captcha_word = captcha_word.strip()
        if not normalized_captcha_word:
            challenge = gibdd_challenges.get(challenge_id)
            if challenge is None:
                return await _start_gibdd_captcha_flow(
                    config=config,
                    request=request,
                    templates=templates,
                    gibdd_check_service=gibdd_check_service,
                    gibdd_challenges=gibdd_challenges,
                    query=query,
                    error_message="Сессия капчи устарела. Введи символы с новой картинки.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            return templates.TemplateResponse(
                request=request,
                name="gibdd_captcha.html",
                context=_gibdd_captcha_context(
                    config=config,
                    request=request,
                    query=query,
                    challenge_id=challenge_id,
                    captcha_image_data_url=_captcha_image_data_url(challenge),
                    error_message="Введи символы с картинки.",
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        challenge = gibdd_challenges.pop(challenge_id)
        if challenge is None:
            return await _start_gibdd_captcha_flow(
                config=config,
                request=request,
                templates=templates,
                gibdd_check_service=gibdd_check_service,
                gibdd_challenges=gibdd_challenges,
                query=query,
                error_message="Сессия капчи устарела. Введи символы с новой картинки.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            report = await gibdd_check_service.check_vin(
                query.value,
                captcha_word=normalized_captcha_word,
                captcha_token=challenge.captcha_token,
                cookies=challenge.cookies,
            )
        except GibddCaptchaError as exc:
            return await _start_gibdd_captcha_flow(
                config=config,
                request=request,
                templates=templates,
                gibdd_check_service=gibdd_check_service,
                gibdd_challenges=gibdd_challenges,
                query=query,
                error_message=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except VehicleCheckError as exc:
            return templates.TemplateResponse(
                request=request,
                name="report.html",
                context=_report_context(
                    config=config,
                    request=request,
                    query=query,
                    report=None,
                    error_message=str(exc),
                ),
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        return templates.TemplateResponse(
            request=request,
            name="report.html",
            context=_report_context(
                config=config,
                request=request,
                query=query,
                report=report,
                error_message="",
            ),
        )

    @app.get("/api/check")
    async def api_check(q: str = "") -> JSONResponse:
        query = parse_vehicle_query(q)
        if query is None:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "ok": False,
                    "error": "invalid_query",
                    "message": "Expected a 17-character VIN or a Russian plate like A123BC77.",
                },
            )

        try:
            report = await _run_vehicle_report(vehicle_check_service, query)
        except VehicleCheckError as exc:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "ok": False,
                    "error": "provider_error",
                    "message": str(exc),
                    "query_type": query.kind,
                    "query_value": query.value,
                },
            )

        return JSONResponse(
            content={
                "ok": True,
                "query_type": report.query_type,
                "query_value": report.query_value,
                "provider": report.provider,
                "checked_at": report.checked_at.astimezone(timezone.utc).isoformat(),
                "summary": report.summary,
                "sections": [
                    {
                        "title": section.title,
                        "lines": list(section.lines),
                    }
                    for section in report.sections
                ],
            },
        )

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True, "service": "autodosie-web"})

    return app


app = build_app()


async def _run_vehicle_report(
    vehicle_check_service: VehicleCheckService,
    query: VehicleQuery,
) -> VehicleCheckReport:
    if query.kind == "vin":
        return await vehicle_check_service.check_vin(query.value)
    return await vehicle_check_service.check_plate(query.value)


async def _start_gibdd_captcha_flow(
    *,
    config: AppConfig,
    request: Request,
    templates: Jinja2Templates,
    gibdd_check_service: GibddCheckService,
    gibdd_challenges: _GibddChallengeStore,
    query: VehicleQuery,
    error_message: str,
    status_code: int,
) -> HTMLResponse:
    try:
        challenge = await gibdd_check_service.begin_vin_check(query.value)
    except VehicleCheckError as exc:
        message = str(exc)
        if error_message and error_message != message:
            message = f"{error_message} {message}"
        elif error_message:
            message = error_message

        return templates.TemplateResponse(
            request=request,
            name="gibdd_captcha.html",
            context=_gibdd_captcha_context(
                config=config,
                request=request,
                query=query,
                challenge_id="",
                captcha_image_data_url="",
                error_message=message,
            ),
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    challenge_id = gibdd_challenges.put(challenge)
    return templates.TemplateResponse(
        request=request,
        name="gibdd_captcha.html",
        context=_gibdd_captcha_context(
            config=config,
            request=request,
            query=query,
            challenge_id=challenge_id,
            captcha_image_data_url=_captcha_image_data_url(challenge),
            error_message=error_message,
        ),
        status_code=status_code,
    )


def _captcha_image_data_url(challenge: GibddCaptchaChallenge) -> str:
    payload = base64.b64encode(challenge.image_bytes).decode("ascii")
    return f"data:image/jpeg;base64,{payload}"


def _render_invalid_query_response(
    *,
    config: AppConfig,
    request: Request,
    templates: Jinja2Templates,
    submitted_query: str,
    error_message: str,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=_base_context(
            config=config,
            active_page="home",
            request=request,
            submitted_query=submitted_query,
            error_message=error_message,
        ),
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _base_context(
    *,
    config: AppConfig,
    active_page: str,
    request: Request,
    submitted_query: str,
    error_message: str,
) -> dict[str, Any]:
    return {
        "active_page": active_page,
        "error_message": error_message,
        "example_plate": _EXAMPLE_PLATE,
        "example_vin": _EXAMPLE_VIN,
        "request": request,
        "site_name": config.site_name,
        "site_url": config.site_url,
        "submitted_query": submitted_query,
        "support_email": "hello@autodosie.ru",
    }


def _gibdd_captcha_context(
    *,
    config: AppConfig,
    request: Request,
    query: VehicleQuery,
    challenge_id: str,
    captcha_image_data_url: str,
    error_message: str,
) -> dict[str, Any]:
    context = _base_context(
        config=config,
        active_page="report",
        request=request,
        submitted_query=query.value,
        error_message=error_message,
    )
    context["query_label"] = "VIN"
    context["query_type"] = "vin"
    context["query_value"] = query.value
    context["challenge_id"] = challenge_id
    context["captcha_image_data_url"] = captcha_image_data_url
    context["gibdd_directions"] = _GIBDD_DIRECTION_LABELS
    context["captcha_refresh_url"] = f"/report/gibdd?q={query.value}"
    context["captcha_retry_after_seconds"] = 60
    context["gibdd_wait_window_seconds"] = int(config.gibdd_captcha_wait_seconds)
    return context


def _report_context(
    *,
    config: AppConfig,
    request: Request,
    query: VehicleQuery,
    report: VehicleCheckReport | None,
    error_message: str,
) -> dict[str, Any]:
    context = _base_context(
        config=config,
        active_page="report",
        request=request,
        submitted_query=query.value,
        error_message=error_message,
    )
    context["query_label"] = "VIN" if query.kind == "vin" else "Госномер"
    context["query_type"] = query.kind
    context["report"] = None
    context["gibdd_check_url"] = f"/report/gibdd?q={query.value}" if query.kind == "vin" else ""
    context["gibdd_action_label"] = "Проверить по ГИБДД"

    if report is None:
        return context

    context["report"] = {
        "checked_at": report.checked_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "provider": report.provider,
        "query_label": "VIN" if report.query_type == "vin" else "Госномер",
        "query_value": report.query_value,
        "sections": report.sections,
        "summary": report.summary,
    }
    if report.provider == "gibdd-official":
        context["gibdd_action_label"] = "Повторить проверку ГИБДД"
    return context
