"""Behavioral tests against the real Modbus model and mock transport."""

import json
from pathlib import Path

import pytest
from modbus_connection import IllegalDataAddressError, ModbusConnectionError
from modbus_connection.mock import MockModbusConnection, MockModbusUnit, WriteEvent

from indevolt_modbus import REGISTERS, IndevoltDevice
from indevolt_modbus.components import COMPONENTS


async def test_microinverter_energy_uses_both_words(unit: MockModbusUnit) -> None:
    """Stray OFF/ON rows must not truncate a documented 32-bit energy counter."""
    unit.holding.update({7545: [1, 2], 7547: [3, 4]})
    device = await IndevoltDevice.async_detect(unit)
    registers = {r.address: r for r in device.registers}
    (reader,) = device.read_groups(registers[a].key for a in (7545, 7547))
    unit.read_events.clear()
    await reader.async_update(notify=False)
    assert unit.read_events[0].address == 7545
    assert unit.read_events[0].count == 4
    assert getattr(reader, registers[7545].key) == 65538
    assert getattr(reader, registers[7547].key) == 196612
    assert not registers[7547].options
    assert registers[7547].unit == "Wh"


@pytest.fixture
def unit() -> MockModbusUnit:
    connection = MockModbusConnection()
    unit = connection.for_unit(1)
    unit.holding.update({70: 14501, 7534: 19})
    return unit


async def test_signed_scaled_and_32_bit_values(unit: MockModbusUnit) -> None:
    unit.holding.update(
        {
            2219: 123,
            2220: 2345,
            2221: 450,
            7512: [1, 2],
            6018: 65526,
            1247: [65535, 65036],
            7599: 765,
        }
    )
    device = await IndevoltDevice.async_detect(unit)
    report = await device.async_update(
        [
            "pv_real_time_data",
            "pv_1",
            "pv_statistics",
            "battery_0_real_time_data",
            "meter_real_time_data",
            "battery_real_time_data",
        ]
    )
    assert report.complete
    expected = {
        2219: 1.23,
        2220: 234.5,
        2221: 450,
        7512: 65538,
        6018: -10,
        1247: -500,
        7599: 76.5,
    }
    for register in device.registers:
        if register.address in expected:
            assert device.value(register) == expected[register.address]


async def test_version_gates_fields_and_enum_writes(unit: MockModbusUnit) -> None:
    unit.holding[7534] = 15
    device = await IndevoltDevice.async_detect(unit)
    assert all(
        r.address not in (7271, 7272, 7599, 7600, 7300) for r in device.registers
    )
    mode = next(r for r in device.registers if r.address == 1144)
    assert device.options(mode) == {1: "Self-consumption", 4: "Realtime Control"}
    with pytest.raises(ValueError, match="enumeration"):
        await device.async_write(mode, 6)


async def test_writes_and_readback(unit: MockModbusUnit) -> None:
    events: list[WriteEvent] = []
    unit.on_write(events.append)
    device = await IndevoltDevice.async_detect(unit)
    backup = next(r for r in device.registers if r.address == 1142)
    await device.async_write(backup, 42)
    assert events[-1].address == 1142
    assert events[-1].values == [42]
    assert events[-1].function_code == 6
    await device.async_update([backup.component])
    assert device.value(backup) == 42
    meter = next(r for r in device.registers if r.address == 1247)
    await device.async_write(meter, -500)
    assert events[-1].values == [65535, 65036]
    assert events[-1].function_code == 16


@pytest.mark.parametrize(
    ("address", "value"),
    [
        (1142, -1),
        (1142, 101),
        (1154, 4),
        (1151, 3601),
        (7270, 99),
        (7268, 61),
        (1152, 50.5),
        (1152, float("nan")),
        (1152, float("inf")),
        (7300, 0x1800),
        (7301, 0x123C),
        (1132, 0),
        (1133, 0),
        (1134, 0x3C00),
        (1150, 99),
        (7303, 3601),
        (7304, 101),
    ],
)
async def test_invalid_writes_never_touch_transport(
    unit: MockModbusUnit, address: int, value: float
) -> None:
    events: list[WriteEvent] = []
    unit.on_write(events.append)
    device = await IndevoltDevice.async_detect(unit)
    register = next(r for r in device.registers if r.address == address)
    with pytest.raises(ValueError):
        await device.async_write(register, value)
    assert events == []


async def test_read_only_field(unit: MockModbusUnit) -> None:
    device = await IndevoltDevice.async_detect(unit)
    register = next(r for r in device.registers if r.address == 70)
    with pytest.raises(AttributeError, match="read-only"):
        await device.async_write(register, 1)


async def test_partial_failure_and_recovery(unit: MockModbusUnit) -> None:
    device = await IndevoltDevice.async_detect(unit)
    unit.fail_read(2219, IllegalDataAddressError())
    report = await device.async_update(["pv_1", "system_info"])
    assert report.updated == {"system_info"}
    assert "pv_1" in report.failed
    unit.fail_read(2219, None)
    assert (await device.async_update(["pv_1"])).complete


async def test_disconnected_link_propagates(unit: MockModbusUnit) -> None:
    device = await IndevoltDevice.async_detect(unit)
    unit.fail_read(70, ModbusConnectionError("offline"))
    with pytest.raises(ModbusConnectionError):
        await device.async_update(["system_info"])


async def test_no_undocumented_gaps_or_string_reads(unit: MockModbusUnit) -> None:
    device = await IndevoltDevice.async_detect(unit)
    unit.read_events.clear()
    reads = unit.read_events
    await device.async_update()
    documented: set[int] = set()
    for component in device.components.values():
        for field in component.resolved_fields.values():
            documented.update(range(field.address, field.address + field.field.count))
    for read in reads:
        assert read.register_type == "holding"
        assert read.count <= 125
        assert set(range(read.address, read.address + read.count)) <= documented
    assert not {6022, 6134, 6246, 6358, 6470, 6745} & documented


async def test_unknown_enum_is_none(unit: MockModbusUnit) -> None:
    unit.holding[1144] = 65535
    device = await IndevoltDevice.async_detect(unit)
    register = next(r for r in device.registers if r.address == 1144)
    await device.async_update([register.component])
    assert device.value(register) is None


def test_catalog_coverage() -> None:
    catalog = json.loads(
        (Path(__file__).parents[1] / "docs/registers.json").read_text()
    )
    assert len(catalog) == 350
    assert len(REGISTERS) == 344
    assert {r.address for r in REGISTERS} == {
        r["address"] for r in catalog if "deferred" not in r
    }
    assert len({r.key for r in REGISTERS}) == len(REGISTERS)
    for register in REGISTERS:
        field = COMPONENTS[register.component].declared_fields[register.key]
        assert field.address == register.address
    assert {r.address for r in REGISTERS} >= set(range(7300, 7420))
    assert {r.address for r in REGISTERS} >= set(range(7080, 7128))


@pytest.mark.parametrize("version", [0, 65535])
async def test_invalid_probe(unit: MockModbusUnit, version: int) -> None:
    unit.holding[7534] = version
    with pytest.raises(ValueError, match="protocol"):
        await IndevoltDevice.async_detect(unit)


async def test_selected_read_groups_are_bounded_and_independent(
    unit: MockModbusUnit,
) -> None:
    device = await IndevoltDevice.async_detect(unit)
    unit.holding.update({6563: 2, 6564: 65526, 7599: 765, 1269: [1, 2]})
    registers = {r.address: r for r in device.registers}
    selected = [registers[a].key for a in (6563, 6564, 7599, 1269)]
    groups = device.read_groups(selected)
    unit.read_events.clear()
    values = {}
    for group in groups:
        before = len(unit.read_events)
        await group.async_update()
        assert len(unit.read_events) == before + 1
        values.update({key: getattr(group, key) for key in group.resolved_fields})
    assert values[registers[6564].key] == -10
    assert values[registers[7599].key] == 76.5
    assert values[registers[1269].key] == 65538
    assert device.value(registers[6564]) is None
    # Building another selection must not permanently narrow device components.
    (reader,) = device.read_groups([registers[6564].key])
    assert set(reader.resolved_fields) == {registers[6564].key}
    assert device.read_groups([]) == []
    with pytest.raises(ValueError, match="Unsupported"):
        device.read_groups(["not_a_register"])


async def test_adjacent_selected_fields_share_one_read(unit: MockModbusUnit) -> None:
    device = await IndevoltDevice.async_detect(unit)
    registers = {r.address: r for r in device.registers}
    groups = device.read_groups(registers[a].key for a in (1150, 1151, 1152))
    assert len(groups) == 1
    unit.read_events.clear()
    await groups[0].async_update()
    assert len(unit.read_events) == 1
    assert unit.read_events[0].address == 1150
    assert unit.read_events[0].count == 3


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, 0), (32767, 32767), (32768, -32768), (63609, -1927), (65535, -1)],
)
async def test_acoutw_signed_decoding(
    unit: MockModbusUnit, raw: int, expected: int
) -> None:
    unit.holding[1284] = raw
    device = await IndevoltDevice.async_detect(unit)
    register = next(r for r in device.registers if r.address == 1284)
    (reader,) = device.read_groups([register.key])
    await reader.async_update(notify=False)
    assert getattr(reader, register.key) == expected


@pytest.mark.parametrize(
    ("ac_raw", "battery_raw", "ac_expected", "battery_expected"),
    [(1927, 63609, 1927, -1927), (63609, 1927, -1927, 1927)],
)
async def test_ac_and_battery_direction_preserved(
    unit: MockModbusUnit,
    ac_raw: int,
    battery_raw: int,
    ac_expected: int,
    battery_expected: int,
) -> None:
    # Charging: AC input positive, battery charging negative. Discharge reverses both.
    unit.holding.update({174: ac_raw, 6564: battery_raw})
    device = await IndevoltDevice.async_detect(unit)
    registers = {r.address: r for r in device.registers}
    for address, expected in ((174, ac_expected), (6564, battery_expected)):
        (reader,) = device.read_groups([registers[address].key])
        await reader.async_update(notify=False)
        assert getattr(reader, registers[address].key) == expected
