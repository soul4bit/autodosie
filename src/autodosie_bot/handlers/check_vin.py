from __future__ import annotations

from datetime import timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from autodosie_bot.services.base import VehicleCheckReport, VehicleCheckService
from autodosie_bot.validation import is_valid_vin, normalize_vin

router = Router(name="check_vin")


class CheckVinStates(StatesGroup):
    waiting_for_vin = State()


def format_report(report: VehicleCheckReport) -> str:
    checked_at = report.checked_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"<b>VIN:</b> <code>{escape(report.vin)}</code>",
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


async def process_vin(
    message: Message,
    state: FSMContext,
    vehicle_check_service: VehicleCheckService,
    raw_vin: str,
) -> None:
    vin = normalize_vin(raw_vin)

    if not is_valid_vin(vin):
        await state.set_state(CheckVinStates.waiting_for_vin)
        await message.answer(
            "Нужен VIN из 17 символов. Допустимы латинские буквы и цифры.\n"
            "Пример: <code>XTA210740Y1234567</code>",
        )
        return

    await state.clear()
    await message.answer(f"Принял VIN <code>{escape(vin)}</code>. Запрос выполняется.")

    report = await vehicle_check_service.check_vin(vin)
    await message.answer(format_report(report))


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

    await state.set_state(CheckVinStates.waiting_for_vin)
    await message.answer("Пришли VIN из 17 символов одним сообщением.")


@router.message(CheckVinStates.waiting_for_vin, F.text)
async def handle_requested_vin(
    message: Message,
    state: FSMContext,
    vehicle_check_service: VehicleCheckService,
) -> None:
    await process_vin(message, state, vehicle_check_service, message.text)


@router.message(CheckVinStates.waiting_for_vin)
async def handle_non_text_vin(message: Message) -> None:
    await message.answer("Нужен текстовый VIN. Просто отправь его сообщением.")


@router.message(F.text.regexp(r"^[A-Za-zА-Яа-я0-9\-\s]{17,24}$"))
async def handle_direct_vin(
    message: Message,
    state: FSMContext,
    vehicle_check_service: VehicleCheckService,
) -> None:
    await process_vin(message, state, vehicle_check_service, message.text)

