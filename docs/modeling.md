# Model choices

The modbus-connection source at the revision recorded in `sources.json` was
reviewed, particularly `model/fields.py`, `model/component.py`, `model/device.py`
and `model/_writing.py`. The minimum tested release is 4.12.4.

Its public field helpers include `gauge`, `integer`, `raw_register`, `uint32`,
`int32`, `uint64`, `int64`, `float32`, `float64`, `string`, `enum`, `flags`,
`boolean`, `bit`, `bits`, `coil`, `discrete_input` and `repeating_group`.
Additional field classes represent IPv4, IPv6 and EUI-48 addresses. None of the
vendor rows requires floating-point wire values, bit-address spaces or network
address fields. A scaled integer is not an IEEE floating-point register.

The generated library declares `NumberField[int]` / `NumberField[float]` with
explicit count, sign, physical unit and fixed scale, plus typed `enum` fields.
`NumberField` is the primitive underlying the numeric helpers. The source's
`acc32` and `bitfield32` use unsigned two-word fields. Raw alarm values preserve
unknown bits rather than inventing a bit numbering convention. String fields
are held back until their counts are known. No arbitrary NaN sentinels are set.

`Component.max_gap = 0` prevents reads across undocumented holes. Multiword
fields stay together and `max_span = 125` enforces the protocol request limit.
Distinct PV channels and optional battery subsystems are separate components.
Schedule and load-profile endpoints are expanded only where the vendor states
the intervening layout explicitly.

The device reads the protocol version at setup, applies `restrict_fields` to
exclude newer registers, and delegates polling to `Device.async_poll` for an
`UpdateReport`. A temporary subsystem exception is retried next time; a broken
connection propagates immediately. Consumers must check the report before
using cached values, which may remain from a preceding successful update.

A callable `writable` validator must return the value to encode, not merely
validate it. The library checks physical bounds before any write, and the
public device method also checks allowed enumeration codes for the installed
protocol. Single registers use FC06, multiword registers FC16. Packed schedule
times are whole-word writes; no read-modify-write is needed. There is no
undocumented multi-register commit operation or implied atomic schedule update.

The caller retains ownership of connection cleanup. The library asks the unit
for message pacing and timeout requirements and never creates a transport.
