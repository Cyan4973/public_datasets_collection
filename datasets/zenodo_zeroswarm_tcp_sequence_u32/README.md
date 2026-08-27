# Zero-SWARM TCP Sequence/Acknowledgment UInt32

This recipe reuses the CC BY 4.0 Zero-SWARM normal Factory I/O captures but
adds a genuinely different 32-bit numeric shape: native TCP sequence-space
trajectories.

TCP sequence and acknowledgment numbers are cumulative byte positions. In
capture order they form long staircases with repeated plateaus and variable
payload-sized jumps. Only the initial connection offsets are randomized; the
millions of following values encode deterministic transport progress,
acknowledgment delay, and repeated packet-state behavior. This differs from the
accepted uint16 register values, packet lengths, receive windows, IPv4 IDs, and
Modbus transaction fields.

The intended output contains eight separate natural samples:

- sequence numbers for request and response packets in each of two captures;
- acknowledgment numbers for request and response packets in each capture.

Fields and directions remain separate. IP/MAC addresses, ports, timestamps,
checksums, TCP flags/options, and packet payload bytes are not emitted.

The exact PCAPs are already present for the accepted uint16 sibling recipe.
This command verifies that cache and hard-links it into the candidate download
directory when possible, avoiding another 250 MB transfer:

```bash
bash staging/zenodo_zeroswarm_tcp_sequence_u32/download.sh
```

If the verified cache is absent, the script falls back to the exact Zenodo
objects. It then performs a complete local PCAP preflight without emitting
training samples.
