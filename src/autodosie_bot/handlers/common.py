from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router(name="common")

HELP_TEXT = (
    "Команды:\n"
    "/start - описание бота\n"
    "/help - подсказка\n"
    "/check - бесплатный отчет по VIN или госномеру\n"
    "/checkvin - бесплатный отчет по VIN\n"
    "/checkgibdd - официальный запрос ГИБДД с капчей\n"
    "/gibdd - короткая команда для ГИБДД\n"
    "/cancel - отменить текущий сценарий ГИБДД\n\n"
    "Можно сразу отправить сообщением:\n"
    "<code>XTA210740Y1234567</code>\n"
    "<code>А123ВС77</code>\n\n"
    "Сейчас /check и /checkvin работают только в РФ-режиме: без американских VIN-источников. "
    "/checkgibdd запускает отдельный официальный поток ГИБДД с капчей."
)


@router.message(CommandStart())
async def command_start(message: Message) -> None:
    await message.answer(
        "Это каркас бота для проверки автомобиля по VIN или госномеру.\n\n"
        "Сейчас бот умеет распознавать оба формата. Для VIN и госномера уже работает бесплатный агрегированный отчет "
        "из доступных открытых источников в РФ-режиме, а для ГИБДД добавлен отдельный официальный сценарий с капчей.\n\n"
        "Используй /check для бесплатного отчета или /checkgibdd для официальной проверки ГИБДД.",
    )


@router.message(Command("help"))
async def command_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message()
async def fallback_message(message: Message) -> None:
    await message.answer(
        "Пока я понимаю команды /start, /help, /check, /checkvin, /checkgibdd и /gibdd, а также прямой VIN или российский госномер.",
    )
