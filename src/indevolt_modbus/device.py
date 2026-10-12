"""An Indevolt storage device composed of typed functional subsystems."""

from collections.abc import Iterable
from typing import Any, Self

from modbus_connection import ModbusUnit
from modbus_connection.model import Device, UpdateReport

from .components import COMPONENTS, SystemInfo
from .model import IndevoltComponent, Register
from .registers import REGISTERS


class IndevoltDevice(Device):
    """Read and control a storage device through a caller-owned Modbus unit.

    Protocol versions use the device's integer convention (19 means V1.9).
    Strings without documented lengths are intentionally excluded. No network
    discovery or model/serial identification is inferred from telemetry.
    """

    def __init__(self, unit: ModbusUnit, *, message_spacing: float = 5.0) -> None:
        super().__init__(unit)
        if message_spacing < 1:
            raise ValueError("The device requires at least one second between requests")
        unit.set_message_spacing(message_spacing)
        unit.require_timeout(2.0)
        self.protocol_version = 0
        self.components: dict[str, IndevoltComponent] = {}
        self.registers: tuple[Register, ...] = ()
        self.system_info = SystemInfo(unit)

    @classmethod
    async def async_detect(cls, unit: ModbusUnit) -> Self:
        """Probe the documented protocol version and build the device."""
        device = cls(unit)
        await device.async_ensure_setup()
        return device

    async def _async_setup(self) -> None:
        await self.system_info.async_update(notify=False)
        version = self.system_info.modbus_version_7534
        if version is None or not 1 <= version <= 99:
            raise ValueError("Invalid Indevolt protocol version")
        self.protocol_version = version
        self.registers = tuple(r for r in REGISTERS if r.minimum_version <= version)
        for name, cls in COMPONENTS.items():
            fields = [r.key for r in self.registers if r.component == name]
            if not fields:
                continue
            component = (
                self.system_info if name == "system_info" else cls(self.modbus_unit)
            )
            component.restrict_fields(fields)
            self.components[name] = component
            setattr(self, name, component)

    async def async_update(self, names: Iterable[str] | None = None) -> UpdateReport:
        """Refresh selected subsystems and report partial failures independently."""
        await self.async_ensure_setup()
        return await self.async_poll(self.components if names is None else names)

    def value(self, register: Register) -> Any:
        """Return a current typed value, or None for an unsupported register."""
        component = self.components.get(register.component)
        return None if component is None else getattr(component, register.key)

    def options(self, register: Register) -> dict[int, str]:
        """Return only enumeration options supported by the protocol version."""
        return {
            value: name
            for value, name in register.options.items()
            if register.option_versions.get(value, 0) <= self.protocol_version
        }

    async def async_write(self, register: Register, value: int | float) -> None:
        """Write a supported field; do not optimistically change its cached value."""
        await self.async_ensure_setup()
        if register not in self.registers:
            raise ValueError("Register is unsupported by this protocol version")
        if register.options and value not in self.options(register):
            raise ValueError("Unsupported enumeration value")
        await self.components[register.component].write(register.key, value)
