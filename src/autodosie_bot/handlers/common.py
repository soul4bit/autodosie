from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router(name="common")

HELP_TEXT = (
    "Команды:\n"
    "/start - описание бота\n"
    "/help - подсказка\n"
    "/check - проверить VIN или госномер\n"
    "/checkvin - базовая проверка VIN\n"
    "/checkgibdd - официальный запрос ГИБДД с капчей\n"
    "/gibdd - короткая команда для ГИБДД\n"
    "/cancel - отменить текущий сценарий ГИБДД\n\n"
    "Можно сразу отправить сообщением:\n"
    "<code>XTA210740Y1234567</code>\n"
    "<code>А123ВС77</code>\n\n"
    "Сейчас /check и /checkvin работают по обычному сценарию бота, а /checkgibdd запускает официальный поток ГИБДД с капчей."
)


@router.message(CommandStart())
async def command_start(message: Message) -> None:
    await message.answer(
        "Это каркас бота для проверки автомобиля по VIN или госномеру.\n\n"
        "Сейчас бот умеет распознавать оба формата. Для VIN уже работает обычная проверка, "
        "для ГИБДД добавлен отдельный официальный сценарий с капчей, а для госномера подготовлен отдельный путь под будущий источник данных.\n\n"
        "Используй /check для обычной проверки или /checkgibdd для официальной проверки ГИБДД.",
    )


@router.message(Command("help"))
async def command_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message()
async def fallback_message(message: Message) -> None:
    await message.answer(
        "Пока я понимаю команды /start, /help, /check, /checkvin, /checkgibdd и /gibdd, а также прямой VIN или российский госномер.",
    )
