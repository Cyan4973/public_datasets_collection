# Zero-SWARM Modbus Read Registers UInt16 Development — 2026-08-01 / 2026-08-03

`zenodo_zeroswarm_modbus_registers_u16` adds a genuinely new native-16-bit
domain: industrial-control protocol register telemetry. The accepted material
is extracted from normal Factory I/O traffic rather than attack or scan
captures.

## Source, selection, and license

Zenodo record `15082260`, *Modbus Normal and Malicious Network Traffic*, was
published by George Lazaridis and Asterios Mpatziakas under CC BY 4.0 with DOI
`10.5281/zenodo.15082260`. The bounded source is:

- `ZeroSWARM Normal data_v2.pcap`
- source bytes: `232,217,247`
- MD5: `eee8b87e62c482fd574b6e78d32cb12b`

The exact record JSON is retained and validated for record ID, title, and
license. The recipe originally used the 18.1 MB `v2b` normal capture, but a
2026-08-03 expansion probe established that the 232 MB `v2` capture provides
14.54 times as many observations per register and substantially broader
holding-register ranges. The smaller streams are not verbatim slices of the
large streams, but they represent the same Factory I/O loop and would add only
6.9% beyond the large run, so `v2` replaces rather than supplements `v2b`.
Flooding and Nmap captures remain excluded because the intended quantity is
normal operational telemetry, not attack mechanics.

## Protocol decoding and selection

The local standard-library parser validates classic Ethernet PCAP, decodes
IPv4/TCP port 502, and recognizes complete Modbus/TCP ADUs. Function-3 holding
register and function-4 input register responses are matched to requests by
client/server flow, transaction ID, unit ID, and function code. This restores
the requested starting address before values are assigned to a register
series.

Preflight decoded 2,840,579 Modbus/TCP packets, 2,367,125 complete ADUs, and
1,420,270 addressed register words. It correlated 473,423 read responses. The
capture also contains exactly seven response ADUs whose requests are absent,
so their start addresses cannot be recovered; they are excluded and the exact
diagnostic count is enforced. Six candidate register streams existed, but the
two function-16 write streams closely mirror holding-register ranges and
transitions, so writes remain excluded to avoid overweighting the control
loop. The four retained samples are:

- unit 1 input registers 0 and 1
- unit 1 holding registers 0 and 1

Whole packet bytes, IP addresses, ports, timestamps, transaction IDs, coil
values, and request parameters are not emitted.

## Transport-header expansion — 2026-08-08

The accepted source was reparsed to add native network-stack telemetry that
was previously excluded from training output. Five new samples preserve packet
order while omitting all endpoint identities:

- IPv4 Identification request: 1,657,009 values, full `[0, 65535]` range
- IPv4 Identification response: 1,183,570 values, full `[0, 65535]` range
- IPv4 Total Length request: 1,657,009 values, four values in `[40, 57]`
- IPv4 Total Length response: 1,183,570 values, three values in `[51, 53]`
- TCP response receive window: 1,183,570 values, seven values in `[8206, 8212]`

Identification fields exhibit sequential counter structure rather than hash-
like noise. Total lengths capture request/response packet-size patterns. The
response window has 76,714 transitions. The constant request window and all
checksums are deliberately excluded, as are IP/MAC addresses, ports,
timestamps, sequence/acknowledgment numbers, and payload framing.

The expansion adds 6,864,728 values and 13,729,456 bytes. Combined accepted
output is now 9 samples, 7,811,574 uint16 values, and 15,623,148 bytes.
Every new sample has exact count, range, cardinality, transition total, and
SHA-256 enforcement, and independent verification reparses and byte-compares
the complete output.

## Native representation and verified output

Modbus registers are protocol-native unsigned 16-bit words. Each retained
word is decoded from network byte order and emitted as the same uint16 value
in little-endian corpus order. Capture and response order are preserved.

- primary samples: `4`
- input-register values per sample: `236,711`
- holding-register values per sample: `236,712`
- total primary values: `946,846`
- input-register bytes per sample: `473,422`
- holding-register bytes per sample: `473,424`
- total primary bytes: `1,893,692`
- input-register range: `[0, 100]`, 101 distinct values per sample
- holding-register ranges: `[3, 423]` and `[3, 311]`, with 421 and 309
  distinct values respectively

Build and verification passed. Verification rechecks source size/MD5 and
Zenodo identity/license metadata, reparses the complete PCAP, reconstructs the
four target register streams independently, and byte-compares all emitted
samples and indexed SHA-256 digests.
