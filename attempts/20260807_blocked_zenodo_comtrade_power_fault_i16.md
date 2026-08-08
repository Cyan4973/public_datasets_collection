# Blocked: Zenodo COMTRADE power-fault int16

- Date: 2026-08-07
- Candidate: `zenodo_comtrade_power_fault_i16`
- Intended domain: electrical-grid fault, relay, and power-quality oscillography
- Intended native width: signed int16 analog samples in COMTRADE `BINARY` DAT records
- Intended natural sample: one complete analog voltage/current channel per event

## Search and validation

A bounded license-first Zenodo search examined 400 unique records across six
COMTRADE power-system queries. It accepted only explicit CC0 or CC BY licenses
and required strong electrical-power semantics rather than generic UN Comtrade
trade-database terminology.

The preflight supported both direct CFG/DAT pairs and ZIP-contained pairs. For
ZIPs it inspected only the central directory and range-extracted small CFG
members. The CFG parser required:

- COMTRADE file type exactly `BINARY`, excluding `ASCII`, `BINARY32`, and
  `FLOAT32`;
- at least one analog channel;
- valid sample-rate segments and declared ending sample;
- DAT size exactly divisible by the COMTRADE record size of the sample number,
  timestamp, signed-int16 analog words, and packed digital-status words; and
- at least 1,000 complete records.

No DAT waveform payload was downloaded.

## Outcome

Only two records combined CC BY 4.0, COMTRADE terminology, and genuine
power-system semantics:

1. Zenodo `6384026`, *Fault Diagnosis of a High Voltage Transmission Line
   Using Waveform Matching Approach*, exposes only `4413ijsc03.pdf` (755,011
   bytes).
2. Zenodo `3603834`, *Use of COMTRADE Fault Current Data to Test Inductive
   Current Transformers*, exposes only `comtrade.pdf` (1,108,341 bytes).

The records discuss COMTRADE data but publish no CFG, DAT, ZIP, or other
waveform container. The remaining apparent matches were unrelated UN Comtrade
trade datasets or lacked a permitted license. Consequently there were zero
matched pairs, zero analog channels, and zero native-int16 payload bytes.

## Retry condition

Do not repeat the broad Zenodo search. Retry only with an exact CC0/CC BY (or
equivalently permissive) public record or repository already known to expose
matched COMTRADE CFG/DAT payloads. The same range-only CFG and byte-geometry
validation can then be reused before downloading waveform data.
