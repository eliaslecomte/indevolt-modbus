"""Validate writes before sending any request."""

import math
from collections.abc import Callable
from typing import Any

RANGES = {
    1138: (100, 10800),
    1142: (0, 100),
    1146: (0, 10800),
    1147: (0, 3600),
    1151: (0, 3600),
    1152: (0, 100),
    1154: (5, 100),
    7268: (0, 60),
    7270: (100, 2400),
}


def validator(address: int) -> Callable[[Any], int]:
    """Return a validator for physical values and packed date/time words.

    Power commands use the documented single-unit limit. Parallel installations
    need a separate, explicitly rated control API before raising this limit.
    """

    def validate(value: Any) -> int:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Expected a finite numeric value")
        if int(value) != value:
            raise ValueError("Expected an integer register value")
        low, high = RANGES.get(address, (0, 65535))
        if address == 1247:
            low, high = -(2**31), 2**31 - 1
        if 7300 <= address <= 7419:
            offset = (address - 7300) % 5
            if offset == 3:
                low, high = 0, 3600
            elif offset == 4:
                low, high = 0, 100
        if not low <= value <= high:
            raise ValueError(f"Value must be in {low}..{high}")
        ranges = {1132: (0, 99, 1, 12), 1133: (1, 31, 0, 23), 1134: (0, 59, 0, 59)}
        if address in (1155, 1156, 7269) or (
            7300 <= address <= 7419 and (address - 7300) % 5 < 2
        ):
            ranges[address] = (0, 23, 0, 59)
        if address in ranges:
            amin, amax, bmin, bmax = ranges[address]
            if not (
                amin <= int(value) >> 8 <= amax and bmin <= int(value) & 255 <= bmax
            ):
                raise ValueError("Invalid packed date/time")
        return int(value)

    return validate
