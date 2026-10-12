"""Regression coverage for disconnects at the firmware's idle deadline."""

from unittest.mock import AsyncMock, patch

import pytest
from modbus_connection import IllegalDataAddressError, ModbusConnectionError
from modbus_connection.mock import MockModbusConnection

from indevolt_modbus.transport import ReadRecoveryUnit


async def test_read_reconnects_after_pacing_interval() -> None:
    unit = MockModbusConnection().for_unit(1)
    read = AsyncMock(side_effect=[ModbusConnectionError("idle socket"), [24]])
    with (
        patch.object(unit, "read_holding_registers", read),
        patch(
            "indevolt_modbus.transport.asyncio.sleep", new_callable=AsyncMock
        ) as sleep,
    ):
        recovered = ReadRecoveryUnit(unit, 5.0)
        assert await recovered.read_holding_registers(7534, 1) == [24]
        assert read.await_count == 2
        read.assert_awaited_with(7534, 1)
        sleep.assert_awaited_once_with(5.0)


async def test_persistent_disconnect_is_not_retried_forever() -> None:
    unit = MockModbusConnection().for_unit(1)
    read = AsyncMock(side_effect=ModbusConnectionError("offline"))
    with (
        patch.object(unit, "read_holding_registers", read),
        patch("indevolt_modbus.transport.asyncio.sleep", new_callable=AsyncMock),
    ):
        with pytest.raises(ModbusConnectionError):
            await ReadRecoveryUnit(unit, 5.0).read_holding_registers(7534, 1)
        assert read.await_count == 2


async def test_device_exceptions_and_writes_are_not_retried() -> None:
    unit = MockModbusConnection().for_unit(1)
    read = AsyncMock(side_effect=IllegalDataAddressError())
    write = AsyncMock(side_effect=ModbusConnectionError("lost acknowledgement"))
    with (
        patch.object(unit, "read_holding_registers", read),
        patch.object(unit, "write_register", write),
        patch(
            "indevolt_modbus.transport.asyncio.sleep", new_callable=AsyncMock
        ) as sleep,
    ):
        recovered = ReadRecoveryUnit(unit, 5.0)
        with pytest.raises(IllegalDataAddressError):
            await recovered.read_holding_registers(7534, 1)
        with pytest.raises(ModbusConnectionError):
            await recovered.write_register(1142, 30)
        read.assert_awaited_once()
        write.assert_awaited_once_with(1142, 30)
        sleep.assert_not_awaited()
