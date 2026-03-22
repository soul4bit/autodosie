from __future__ import annotations

import re

VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
PLATE_ALLOWED_LETTERS = "ABEKMHOPCTYX"
PLATE_PATTERN = re.compile(rf"^[{PLATE_ALLOWED_LETTERS}]\d{{3}}[{PLATE_ALLOWED_LETTERS}]{{2}}\d{{2,3}}$")
CYRILLIC_VIN_MAP = {
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Х": "X",
}


def normalize_vin(value: str) -> str:
    characters: list[str] = []

    for char in value.strip().upper():
        if char in {" ", "-"}:
            continue
        characters.append(CYRILLIC_VIN_MAP.get(char, char))

    return "".join(characters)


def is_valid_vin(value: str) -> bool:
    return bool(VIN_PATTERN.fullmatch(normalize_vin(value)))


def normalize_plate(value: str) -> str:
    characters: list[str] = []

    for char in value.strip().upper():
        if char in {" ", "-"}:
            continue
        characters.append(CYRILLIC_VIN_MAP.get(char, char))

    return "".join(characters)


def is_valid_plate(value: str) -> bool:
    return bool(PLATE_PATTERN.fullmatch(normalize_plate(value)))
