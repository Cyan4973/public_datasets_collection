# Zero-SWARM Modbus/TCP UInt16 Telemetry

This candidate targets protocol-native unsigned 16-bit register values from
the CC BY 4.0 Zenodo record *Modbus Normal and Malicious Network Traffic*
(`10.5281/zenodo.15082260`).

The recipe uses the 232.2 MB normal-traffic capture. The local
inspector recognizes classic PCAP, Ethernet, IPv4, TCP port 502, and complete
Modbus/TCP ADUs. It counts holding/input-register reads and single/multiple
register writes, correlates read responses with their requests to recover
register addresses, and reports value/range/series statistics.

The build emits four server-read sequences: input registers 0 and 1 contain
236,711 observations each, while holding registers 0 and 1 contain 236,712
observations each, all in packet order. Seven unmatched response ADUs are
excluded because no request is available to recover their register addresses;
that exact count is enforced. Write sequences are intentionally excluded
because they closely mirror the holding-register ranges and transitions.
The same packet pass also emits five transport-header samples: request and
response IPv4 Identification counters, request and response IPv4 Total Length,
and the server-response TCP receive window. These are native network-order
uint16 fields converted to little endian. The request window is excluded
because it is constant. Checksums are excluded because they are intentionally
noise-like; packet bytes, timestamps, addresses, ports, transaction IDs,
sequence/acknowledgment numbers, and coil values are not emitted.

Run:

```bash
bash datasets/zenodo_zeroswarm_modbus_registers_u16/download.sh
bash datasets/zenodo_zeroswarm_modbus_registers_u16/inspect.sh
bash datasets/zenodo_zeroswarm_modbus_registers_u16/build.sh
bash datasets/zenodo_zeroswarm_modbus_registers_u16/verify.sh
```

The exact source object, size, MD5, record identity, and CC BY 4.0 declaration
are validated before extraction.

Validated output: nine samples, 7,811,574 uint16 values, and 15,623,148 bytes.
