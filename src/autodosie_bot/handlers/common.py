from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router(name="common")

HELP_TEXT = (
    "Команды:\n"
    "/start - описание бота\n"
    "/help - подсказка\n"
    "/checkvin - начать проверку VIN\n\n"
    "Можно сразу отправить VIN сообщением или командой:\n"
    "<code>/checkvin XTA210740Y1234567</code>\n\n"
    "Сейчас подключен каркас. Реальную интеграцию с источниками данных подключим следующим этапом."
)


@router.message(CommandStart())
async def command_start(message: Message) -> None:
    await message.answer(
        "Это каркас бота для проверки автомобиля по VIN.\n\n"
        "Сейчас бот принимает VIN, валидирует его и проходит полный путь запроса."
        "\nДальше подключим реальный источник данных.\n\n"
        "Используй /checkvin или сразу пришли VIN.",
    )


@router.message(Command("help"))
async def command_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message()
async def fallback_message(message: Message) -> None:
    await message.answer(
        "Пока я понимаю команды /start, /help, /checkvin и прямой VIN из 17 символов.",
    )

