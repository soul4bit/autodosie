from __future__ import annotations

from aiogram import Router

from autodosie_bot.handlers.check_vin import router as check_vin_router
from autodosie_bot.handlers.common import router as common_router


def get_routers() -> list[Router]:
    return [
        check_vin_router,
        common_router,
    ]

