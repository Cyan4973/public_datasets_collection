# Zero-SWARM Modbus Read Registers UInt16 Development — 2026-08-01

`zenodo_zeroswarm_modbus_registers_u16` adds a genuinely new native-16-bit
domain: industrial-control protocol register telemetry. The accepted material
is extracted from normal Factory I/O traffic rather than attack or scan
captures.

## Source, selection, and license

Zenodo record `15082260`, *Modbus Normal and Malicious Network Traffic*, was
published by George Lazaridis and Asterios Mpatziakas under CC BY 4.0 with DOI
`10.5281/zenodo.15082260`. The bounded source is:

- `ZeroSWARM Normal data_v2b.pcap`
- source bytes: `18,119,840`
- MD5: `9f8235fcdbfcacb32e7a70db14fc6c74`

The exact record JSON is retained and validated for record ID, title, and
license. A larger 232 MB normal capture was not needed. Flooding and Nmap
captures were excluded because the intended quantity is normal operational
telemetry, not attack mechanics. Three unrelated Wi-Fi PCAP search results
were rejected as metadata-query false positives.

## Protocol decoding and selection

The local standard-library parser validates classic Ethernet PCAP, decodes
IPv4/TCP port 502, and recognizes complete Modbus/TCP ADUs. Function-3 holding
register and function-4 input register responses are matched to requests by
client/server flow, transaction ID, unit ID, and function code. This restores
the requested starting address before values are assigned to a register
series.

Preflight decoded 195,362 Modbus/TCP packets, 162,801 complete ADUs, and 97,680
addressed register words. All 32,560 target read responses were correlated;
none was uncorrelated. Six candidate register streams existed, but the two
function-16 write streams closely mirrored holding-register ranges and
transition counts, so writes were excluded to avoid overweighting the control
loop. The four retained samples are:

- unit 1 input registers 0 and 1
- unit 1 holding registers 0 and 1

Packet bytes, IP addresses, ports, timestamps, transaction IDs, protocol
framing, coil values, and request parameters are not emitted.

## Native representation and verified output

Modbus registers are protocol-native unsigned 16-bit words. Each retained
word is decoded from network byte order and emitted as the same uint16 value
in little-endian corpus order. Capture and response order are preserved.

- primary samples: `4`
- values per sample: `16,280`
- total primary values: `65,120`
- bytes per sample: `32,560`
- total primary bytes: `130,240`
- input-register range: `[0, 100]`, 101 distinct values per sample
- holding-register ranges: `[18, 76]` and `[18, 74]`

Build and verification passed. Verification rechecks source size/MD5 and
Zenodo identity/license metadata, reparses the complete PCAP, reconstructs the
four target register streams independently, and byte-compares all emitted
samples and indexed SHA-256 digests.
