# indevolt-modbus

A standalone, typed Python library for reading and controlling Indevolt energy
storage devices over Modbus. The caller supplies a `modbus_connection.ModbusUnit`
and owns the connection. Functional subsystems use `Component` fields, and
`IndevoltDevice` combines them with partial-failure reporting.

Repository: [eliaslecomte/indevolt-modbus](https://github.com/eliaslecomte/indevolt-modbus).

## Install

Requires Python 3.12 or newer. From this checkout:

```sh
pip install .
```

The package is not yet published. The release workflow builds a versioned wheel
and source archive and publishes them through PyPI Trusted Publishing.

## Read a device

Enable Modbus server mode in the Indevolt app. The documented TCP defaults are
port **8899** and unit **1**. The vendor currently describes physical RTU support
as forthcoming; the library accepts a serial unit but hardware support must be
confirmed for the installed firmware.

```python
from indevolt_modbus import IndevoltDevice

# unit comes from your modbus-connection backend/connection.
device = await IndevoltDevice.async_detect(unit)
report = await device.async_update(["inverter_real_time_data"])
for register in device.registers:
    if register.component in report.updated:
        print(register.name, device.value(register), register.unit)
```

Use typed subsystem attributes directly, for example
`device.system_info.modbus_version_7534`. Other subsystem classes are exported
from `indevolt_modbus.components`. `device.components` exposes the active models;
`REGISTERS` describes their public attributes. Values are `None` before a read
or when a known enumeration receives an unknown code.

```sh
uv sync
uv run script/query.py 192.168.1.50 --port 8899 --unit 1 --component inverter_real_time_data
uv run script/query.py 192.168.1.50 --port 8899 --raw --component system_info
```

Raw output contains unredacted device data. A full poll can take several minutes:
the library requests five seconds of spacing around Modbus messages, following
the vendor recommendation. Select the components you need. An explicit
`message_spacing` of at least one second is supported for bench testing.

## Writes

```python
register = next(r for r in device.registers if r.address == 1142)
await device.async_write(register, 20)  # Backup SoC, percent
await device.async_update([register.component])  # Read back actual state
```

Read-only fields reject writes. Numeric values must be finite integers within
the documented range, or the wire type's range where no narrower limit is
published. Packed dates/times are validated. Enumerations and protocol-version
gates are enforced by `async_write`. Power commands at 1151 and in schedule
slots use the single-unit 3600 W limit; parallel-system overrides are not exposed.
Direct component writes enforce field validation but callers should use
`async_write` for protocol-version-dependent enumeration restrictions.

## Register coverage and source decisions

[Register catalog](docs/registers.json) records all 194 explicit source rows,
plus the documented intervening load-profile and schedule points (350 entries).
344 numeric fields are implemented. Six serial fields remain catalog-only:
the source does not specify their length. No serial length or product identity
is guessed. Alarm words remain raw 32-bit integers because the source's `Value`
column does not state its bit-index convention. Multiword values use big-endian
word order, pending a real-device capture. The source does not specify a word
swap. Scales, signedness and zero-based addresses are used as published.

Register 7592 is labeled “Grid voltage” but has Hz units and a 0.01 scale; its
catalog label is preserved. The power-factor unit `Pct` and 0.001 scale are also
preserved, without assuming percent versus ratio. Capacity register 89 is not
an accumulated-energy counter. Unsupported fields are removed before polling
using protocol version register 7534. Optional/unavailable subsystems report
failures independently; temporary failures are retried on subsequent polls.

The linked vendor page contained a Markdown table, not a device YAML, when this
library was prepared. The JSON catalog is the reviewed, deterministic input to
`script/generate.py`. Source revisions are in [sources.json](docs/sources.json).
See the [vendor register table](https://docs.indevolt.com/docs/hardware/open-data/modbus-register-table/)
and [communication guide](https://docs.indevolt.com/docs/hardware/open-data/modbus/).

## Development

Layout, query helper, CI, release workflow and release procedure follow
[sofar-modbus](https://github.com/darkrain-nl/sofar-modbus). Runtime modeling uses
[modbus-connection](https://github.com/home-assistant-libs/modbus-connection).

```sh
uv sync
uv run script/generate.py
uv run ruff check --fix .
uv run ruff format .
uv run ruff check .
uv run mypy
uv run pytest
uv build
```

Two misplaced inverter fault continuation rows under grid charging were moved
to the inverter alarm catalog; grid charging uses its explicitly documented
0/1 values.

Hardware behavior has not been verified. Tests use the actual modbus-connection
mock backend; community captures are needed to resolve the documented gaps.
See [RELEASING.md](RELEASING.md) for publishing setup.

## Selective reads

After `await device.async_ensure_setup()`, `device.read_groups(register_keys)` returns
independent typed readers. Each reader covers one contiguous block of selected,
supported fields (at most 125 registers), with no undocumented gaps. Call
`await reader.async_update()` and read decoded attributes from that reader. Its
cache is independent of `device.value()` and the full subsystem caches. This lets
callers prioritize writes and fast telemetry between individual read requests
without narrowing the device's writable fields. Schedule all access through one
worker/connection and respect the device's message spacing.

### Directional AC power correction

The [vendor register table](https://docs.indevolt.com/docs/hardware/open-data/modbus-register-table/)
checked on 2026-10-15 labels **ACOutW (1284)** as `uint16`, while its
description defines directional inverter-plus-bypass power. A user hardware
capture reported raw `63609`, consistent with signed `-1927 W` (`63609 - 65536`).
The canonical catalog therefore overrides this field to `int16`, retaining the
vendor type and rationale in `source_data_type` and `type_override_reason`.
Generated decoding uses two's complement without reversing the sign.

- **174, inverter AC power:** positive = AC charging/input; negative = AC discharging/output.
- **6564, battery power:** positive = battery discharge; negative = battery charge.
- **1284, total AC power:** inverter power plus bypass power; the vendor describes
  bypass as positive for EPS and negative for a microinverter.

Registers 174 and 6564 remain signed and retain their distinct conventions.
