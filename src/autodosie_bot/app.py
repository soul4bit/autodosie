from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from autodosie_bot.config import load_config
from autodosie_bot.handlers import get_routers
from autodosie_bot.logging_config import configure_logging
from autodosie_bot.services.factory import build_vehicle_check_service


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())

    for router in get_routers():
        dispatcher.include_router(router)

    return dispatcher


async def run() -> None:
    config = load_config()
    configure_logging(config.log_level)

    dispatcher = build_dispatcher()
    vehicle_check_service = build_vehicle_check_service(config)

    async with Bot(
        token=config.bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    ) as bot:
        await dispatcher.start_polling(
            bot,
            config=config,
            vehicle_check_service=vehicle_check_service,
        )

