from __future__ import annotations

from datetime import timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from autodosie_bot.config import AppConfig, load_config
from autodosie_bot.logging_config import configure_logging
from autodosie_bot.query import VehicleQuery, parse_vehicle_query
from autodosie_bot.services.base import VehicleCheckError, VehicleCheckReport, VehicleCheckService
from autodosie_bot.services.factory import build_vehicle_check_service

_PACKAGE_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _PACKAGE_DIR / "templates"
_STATIC_DIR = _PACKAGE_DIR / "static"
_EXAMPLE_VIN = "XTA210740Y1234567"
_EXAMPLE_PLATE = "A123BC77"


def build_app() -> FastAPI:
    config = load_config(require_bot_token=False)
    configure_logging(config.log_level)
    vehicle_check_service = build_vehicle_check_service(config)

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

    @app.get("/report", response_class=HTMLResponse)
    async def report_page(request: Request, q: str = "") -> HTMLResponse:
        query = parse_vehicle_query(q)
        if query is None:
            context = _base_context(
                config=config,
                active_page="home",
                request=request,
                submitted_query=q,
                error_message=(
                    "Нужен VIN из 17 символов или российский госномер в формате A123BC77 либо A123BC777."
                ),
            )
            return templates.TemplateResponse(
                request=request,
                name="index.html",
                context=context,
                status_code=status.HTTP_400_BAD_REQUEST,
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
    }


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
    return context
