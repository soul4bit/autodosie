from __future__ import annotations

import logging
import re
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, Message

from autodosie_bot.handlers.check_vin import format_report
from autodosie_bot.services.base import VehicleCheckError
from autodosie_bot.services.gibdd import GibddCaptchaChallenge, GibddCaptchaError, GibddCheckService
from autodosie_bot.validation import is_valid_vin, normalize_vin

router = Router(name="check_gibdd")
logger = logging.getLogger(__name__)
CAPTCHA_PATTERN = re.compile(r"^\d{5}$")


class GibddCheckStates(StatesGroup):
    waiting_for_vin = State()
    waiting_for_captcha = State()


async def _send_captcha(
    message: Message,
    state: FSMContext,
    challenge: GibddCaptchaChallenge,
    *,
    retry: bool,
) -> None:
    await state.set_state(GibddCheckStates.waiting_for_captcha)
    await state.set_data(
        {
            "vin": challenge.vin,
            "captcha_token": challenge.captcha_token,
            "captcha_cookies": challenge.cookies,
        },
    )

    caption = (
        "Введи 5 цифр с картинки одним сообщением.\n"
        "Для отмены отправь /cancel."
    )
    if retry:
        caption = (
            "Капча оказалась неверной или устарела. Получил новую.\n\n"
            + caption
        )

    await message.answer_photo(
        photo=BufferedInputFile(challenge.image_bytes, filename="gibdd-captcha.jpg"),
        caption=caption,
    )


async def _start_gibdd_flow(
    message: Message,
    state: FSMContext,
    gibdd_check_service: GibddCheckService,
    raw_vin: str,
) -> None:
    vin = normalize_vin(raw_vin)
    if not is_valid_vin(vin):
        await state.set_state(GibddCheckStates.waiting_for_vin)
        await message.answer(
            "Для официальной проверки ГИБДД нужен VIN из 17 символов.\n"
            "Пример: <code>XTA210740Y1234567</code>",
        )
        return

    await message.answer(
        "Готовлю официальный запрос ГИБДД для "
        f"<code>{escape(vin)}</code>. "
        f"Если их сервис лагает, подожду капчу до {int(gibdd_check_service.captcha_wait_seconds)} сек.",
    )

    try:
        challenge = await gibdd_check_service.begin_vin_check(vin)
    except VehicleCheckError as exc:
        await state.clear()
        await message.answer(f"Не удалось получить капчу ГИБДД: {escape(str(exc))}")
        return
    except Exception:
        logger.exception("Unexpected failure while starting GIBDD flow for %s", vin)
        await state.clear()
        await message.answer("Не удалось начать проверку ГИБДД из-за внутренней ошибки.")
        return

    await _send_captcha(message, state, challenge, retry=False)


@router.message(Command(commands=["checkgibdd", "gibdd"]))
async def command_check_gibdd(
    message: Message,
    state: FSMContext,
    command: CommandObject,
    gibdd_check_service: GibddCheckService,
) -> None:
    if command.args:
        await _start_gibdd_flow(message, state, gibdd_check_service, command.args)
        return

    await state.set_state(GibddCheckStates.waiting_for_vin)
    await message.answer(
        "Пришли VIN из 17 символов, и я начну официальную проверку ГИБДД через капчу.",
    )


@router.message(Command("cancel"), StateFilter(GibddCheckStates.waiting_for_vin, GibddCheckStates.waiting_for_captcha))
async def command_cancel_gibdd(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()
    await message.answer("Проверка ГИБДД отменена.")


@router.message(GibddCheckStates.waiting_for_vin, F.text)
async def handle_requested_gibdd_vin(
    message: Message,
    state: FSMContext,
    gibdd_check_service: GibddCheckService,
) -> None:
    await _start_gibdd_flow(message, state, gibdd_check_service, message.text)


@router.message(GibddCheckStates.waiting_for_vin)
async def handle_non_text_gibdd_vin(message: Message) -> None:
    await message.answer("Нужен текстовый VIN из 17 символов.")


@router.message(GibddCheckStates.waiting_for_captcha, F.text)
async def handle_gibdd_captcha(
    message: Message,
    state: FSMContext,
    gibdd_check_service: GibddCheckService,
) -> None:
    captcha_word = message.text.strip()
    if not CAPTCHA_PATTERN.fullmatch(captcha_word):
        await message.answer("Нужны ровно 5 цифр с картинки. Для отмены отправь /cancel.")
        return

    data = await state.get_data()
    vin = str(data.get("vin", "")).strip()
    captcha_token = str(data.get("captcha_token", "")).strip()
    captcha_cookies = data.get("captcha_cookies")

    if not vin or not captcha_token or not isinstance(captcha_cookies, dict):
        await state.clear()
        await message.answer("Сессия проверки ГИБДД потеряна. Запусти /checkgibdd заново.")
        return

    await message.answer(f"Капча принята. Выполняю официальный запрос ГИБДД по <code>{escape(vin)}</code>.")

    try:
        report = await gibdd_check_service.check_vin(
            vin=vin,
            captcha_word=captcha_word,
            captcha_token=captcha_token,
            cookies={str(key): str(value) for key, value in captcha_cookies.items()},
        )
    except GibddCaptchaError as exc:
        logger.info("GIBDD captcha rejected for %s: %s", vin, exc)
        try:
            challenge = await gibdd_check_service.begin_vin_check(vin)
        except VehicleCheckError as refresh_exc:
            await state.clear()
            await message.answer(
                "Капча ГИБДД была отклонена, но не удалось получить новую: "
                f"{escape(str(refresh_exc))}",
            )
            return
        except Exception:
            logger.exception("Unexpected failure while refreshing GIBDD captcha for %s", vin)
            await state.clear()
            await message.answer("Капча ГИБДД была отклонена, и обновить ее не удалось.")
            return

        await _send_captcha(message, state, challenge, retry=True)
        return
    except VehicleCheckError as exc:
        await state.clear()
        await message.answer(f"Не удалось выполнить проверку ГИБДД: {escape(str(exc))}")
        return
    except Exception:
        logger.exception("Unexpected GIBDD check failure for %s", vin)
        await state.clear()
        await message.answer("Проверка ГИБДД завершилась внутренней ошибкой. Повтори запрос позже.")
        return

    await state.clear()
    await message.answer(format_report(report))


@router.message(GibddCheckStates.waiting_for_captcha)
async def handle_non_text_gibdd_captcha(message: Message) -> None:
    await message.answer("Нужны 5 цифр с картинки текстовым сообщением. Для отмены отправь /cancel.")
