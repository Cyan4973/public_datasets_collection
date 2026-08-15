# UCI MetroPT-3 digital states U8 — staging

This candidate targets the documented digital control-state timelines in the
MetroPT-3 air-compressor telemetry table. It will emit one complete time-ordered
uint8 sequence per qualifying state field, never CSV text bytes.

First acquire and profile the official UCI source:

```bash
bash datasets/uci_metropt3_digital_states_u8/download.sh
```

The script validates UCI dataset 791, DOI `10.24432/C5VW3R`, and CC BY 4.0;
pins the archive and extracted CSV identities; and scans every source column.
It reports only fields whose complete observed values are nonmissing integral
codes in 0..255 with at most 256 distinct values. The final series selection
was reviewed as the eight documented digital sensors, all strictly binary.

Build and independently verify the eight timelines with:

```bash
bash datasets/uci_metropt3_digital_states_u8/inspect.sh
bash datasets/uci_metropt3_digital_states_u8/build.sh
bash datasets/uci_metropt3_digital_states_u8/verify.sh
```

Each output is one complete 1,516,948-observation sensor timeline. The eight
samples total 12,135,584 bytes and deliberately preserve long operational runs
and sparse state transitions.
