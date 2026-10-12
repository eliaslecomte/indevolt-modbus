"""Recover reads when device firmware closes an idle TCP connection."""

import asyncio
from typing import Any

from modbus_connection import ModbusConnectionError, ModbusUnit


class ReadRecoveryUnit:
    """Delegate unit operations, retrying a disconnected holding read once.

    Some firmware closes a connection around the recommended five-second
    request interval. Wait out the pacing interval before retrying so the
    backend opens its replacement socket immediately before sending, rather
    than leaving that new socket idle during its pacing delay. Writes are
    delegated unchanged: a lost acknowledgement must never replay a command.
    """

    def __init__(self, unit: ModbusUnit, message_spacing: float) -> None:
        self._unit = unit
        self._message_spacing = message_spacing

    def __getattr__(self, name: str) -> Any:
        """Preserve the caller-owned unit's other operations and lifecycle."""
        return getattr(self._unit, name)

    async def read_holding_registers(self, address: int, count: int) -> list[int]:
        """Retry one idempotent read after a connection loss."""
        try:
            return await self._unit.read_holding_registers(address, count)
        except ModbusConnectionError:
            await asyncio.sleep(self._message_spacing)
            return await self._unit.read_holding_registers(address, count)
