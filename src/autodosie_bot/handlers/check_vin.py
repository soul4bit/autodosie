from __future__ import annotations

import logging
from datetime import timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from autodosie_bot.services.base import VehicleCheckError, VehicleCheckReport, VehicleCheckService
from autodosie_bot.validation import (
    is_valid_plate,
    is_valid_vin,
    normalize_plate,
    normalize_vin,
)

router = Router(name="check_vin")
logger = logging.getLogger(__name__)


class CheckVehicleStates(StatesGroup):
    waiting_for_query = State()
    waiting_for_vin = State()


def format_report(report: VehicleCheckReport) -> str:
    checked_at = report.checked_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    label = "VIN" if report.query_type == "vin" else "Госномер"
    lines = [
        f"<b>{label}:</b> <code>{escape(report.query_value)}</code>",
        f"<b>Источник:</b> {escape(report.provider)}",
        f"<b>Проверка:</b> {escape(checked_at)}",
        "",
        escape(report.summary),
    ]

    for section in report.sections:
        lines.append("")
        lines.append(f"<b>{escape(section.title)}</b>")
        for item in section.lines:
            lines.append(f"- {escape(item)}")

    return "\n".join(lines)


async def run_vin_check(
    message: Message,
    vehicle_check_service: VehicleCheckService,
    vin: str,
) -> None:
    await message.answer(f"Принял VIN <code>{escape(vin)}</code>. Запрос выполняется.")
    try:
        report = await vehicle_check_service.check_vin(vin)
    except VehicleCheckError as exc:
        await message.answer(f"Не удалось выполнить проверку VIN: {escape(str(exc))}")
        return
    except Exception:
        logger.exception("Unexpected VIN check failure for %s", vin)
        await message.answer("Проверка VIN завершилась внутренней ошибкой. Повтори запрос позже.")
        return

    await message.answer(format_report(report))


async def run_plate_check(
    message: Message,
    vehicle_check_service: VehicleCheckService,
    plate: str,
) -> None:
    await message.answer(
        f"Принял госномер <code>{escape(plate)}</code>. "
        "Пока выполняю промежуточный сценарий до подключения реального источника.",
    )
    try:
        report = await vehicle_check_service.check_plate(plate)
    except VehicleCheckError as exc:
        await message.answer(f"Не удалось выполнить проверку номера: {escape(str(exc))}")
        return
    except Exception:
        logger.exception("Unexpected plate check failure for %s", plate)
        await message.answer("Проверка номера завершилась внутренней ошибкой. Повтори запрос позже.")
        return

    await message.answer(format_report(report))


async def process_vin(
    message: Message,
    state: FSMContext,
    vehicle_check_service: VehicleCheckService,
    raw_vin: str,
) -> None:
    vin = normalize_vin(raw_vin)

    if not is_valid_vin(vin):
        await state.set_state(CheckVehicleStates.waiting_for_vin)
        await message.answer(
            "Нужен VIN из 17 символов. Допустимы латинские буквы и цифры.\n"
            "Пример: <code>XTA210740Y1234567</code>",
        )
        return

    await state.clear()
    await run_vin_check(message, vehicle_check_service, vin)


async def process_vehicle_query(
    message: Message,
    state: FSMContext,
    vehicle_check_service: VehicleCheckService,
    raw_value: str,
) -> None:
    vin = normalize_vin(raw_value)
    if is_valid_vin(vin):
        await state.clear()
        await run_vin_check(message, vehicle_check_service, vin)
        return

    plate = normalize_plate(raw_value)
    if is_valid_plate(plate):
        await state.clear()
        await run_plate_check(message, vehicle_check_service, plate)
        return

    await state.set_state(CheckVehicleStates.waiting_for_query)
    await message.answer(
        "Пришли VIN из 17 символов или российский госномер в формате "
        "<code>А123ВС77</code> либо <code>А123ВС777</code>.",
    )


@router.message(Command("check"))
async def command_check(
    message: Message,
    state: FSMContext,
    command: CommandObject,
    vehicle_check_service: VehicleCheckService,
) -> None:
    if command.args:
        await process_vehicle_query(message, state, vehicle_check_service, command.args)
        return

    await state.set_state(CheckVehicleStates.waiting_for_query)
    await message.answer("Пришли VIN или российский госномер одним сообщением.")


@router.message(Command("checkvin"))
async def command_check_vin(
    message: Message,
    state: FSMContext,
    command: CommandObject,
    vehicle_check_service: VehicleCheckService,
) -> None:
    if command.args:
        await process_vin(message, state, vehicle_check_service, command.args)
        return

    await state.set_state(CheckVehicleStates.waiting_for_vin)
    await message.answer("Пришли VIN из 17 символов одним сообщением.")


@router.message(CheckVehicleStates.waiting_for_query, F.text)
async def handle_requested_query(
    message: Message,
    state: FSMContext,
    vehicle_check_service: VehicleCheckService,
) -> None:
    await process_vehicle_query(message, state, vehicle_check_service, message.text)


@router.message(CheckVehicleStates.waiting_for_vin, F.text)
async def handle_requested_vin(
    message: Message,
    state: FSMContext,
    vehicle_check_service: VehicleCheckService,
) -> None:
    await process_vin(message, state, vehicle_check_service, message.text)


@router.message(CheckVehicleStates.waiting_for_query)
async def handle_non_text_query(message: Message) -> None:
    await message.answer("Нужен текстовый VIN или российский госномер.")


@router.message(CheckVehicleStates.waiting_for_vin)
async def handle_non_text_vin(message: Message) -> None:
    await message.answer("Нужен текстовый VIN. Просто отправь его сообщением.")


@router.message(StateFilter(None), F.text.regexp(r"^[A-Za-zАВЕКМНОРСТУХавекмнорстух0-9\-\s]{6,24}$"))
async def handle_direct_vehicle_query(
    message: Message,
    state: FSMContext,
    vehicle_check_service: VehicleCheckService,
) -> None:
    await process_vehicle_query(message, state, vehicle_check_service, message.text)
