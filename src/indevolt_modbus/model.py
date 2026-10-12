"""Common component behavior and register metadata."""

from dataclasses import dataclass, field

from modbus_connection.model import Component


class IndevoltComponent(Component):
    """A functional subsystem; never read through undocumented address gaps."""

    max_gap = 0
    max_span = 125


@dataclass(frozen=True)
class Register:
    """Public metadata for one typed component attribute."""

    key: str
    component: str
    name: str
    address: int
    unit: str | None
    group: str
    minimum_version: int = 0
    writable: bool = False
    options: dict[int, str] = field(default_factory=dict)
    option_versions: dict[int, int] = field(default_factory=dict)
