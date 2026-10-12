#!/usr/bin/env python3
"""Query an Indevolt device and print decoded values or raw registers."""

import argparse
import asyncio
import json

from modbus_connection import ModbusError
from modbus_connection.cli_helper import add_connection_args, connect_from_args

from indevolt_modbus import IndevoltDevice


async def main() -> int:
    """Open a link, query the device and close the caller-owned connection."""
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_args(parser, connections=(("tcp", "socket"), ("serial", "rtu")))
    parser.set_defaults(port=8899)
    parser.add_argument("--unit", type=int, default=1)
    parser.add_argument("--component", action="append", help="Restrict the poll")
    parser.add_argument("--raw", action="store_true")
    args = parser.parse_args()
    connection = await connect_from_args(args)
    try:
        device = await IndevoltDevice.async_detect(connection.for_unit(args.unit))
        names = args.component or list(device.components)
        if unknown := set(names) - device.components.keys():
            parser.error(f"Unknown components: {', '.join(sorted(unknown))}")
        if args.raw:
            print(json.dumps(await device.async_read_raw(names), indent=2))
            return 0
        report = await device.async_update(names)
        for register in device.registers:
            if register.component in report.updated:
                print(f"{register.component}.{register.key}: {device.value(register)}")
        for name, error in report.failed.items():
            print(f"{name}: {error}")
        return 0 if report.complete else 1
    except (ModbusError, ValueError) as error:
        print(f"Cannot read device: {error}")
        return 1
    finally:
        await connection.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
