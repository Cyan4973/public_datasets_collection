# UCI MetroPT-3 digital states uint8 development — 2026-08-15

## Outcome

Accepted `uci_metropt3_digital_states_u8`, the eight documented binary digital
sensor timelines from the MetroPT-3 railway air-compressor telemetry dataset.
The official UCI record is dataset 791, DOI `10.24432/C5VW3R`, distributed
under CC BY 4.0.

## Domain and representation

This family adds real industrial control telemetry rather than another image,
label raster, annotation stream, or opaque protocol byte sequence. MetroPT-3
contains seven analog measurements and eight digital signals sampled in one
time-ordered table. Only the documented digital signals are retained:

- `COMP`: air-intake valve electrical state;
- `DV_eletric`: compressor outlet-valve state;
- `Towers`: active air-dryer tower selector;
- `MPG`: loaded-operation request state;
- `LPS`: low-pressure switch;
- `Pressure_switch`: drying-tower discharge switch;
- `Oil_level`: low-oil switch; and
- `Caudal_impulses`: sampled air-flow pulse output.

Every selected source value is exactly `0.0` or `1.0`, with no missing values.
The recipe writes the corresponding integer state as uint8 without remapping
or changing source row order. One complete sensor timeline is one natural
sample. The blank CSV index, timestamp, analog fields, failure descriptions,
and CSV syntax are excluded.

This is also distinct from the earlier EPC2 MetroPT experiment: it does not
train on ASCII CSV bytes or reproduce a selected multicolumn projection. Each
sample is one homogeneous typed signal, so compression cannot depend on
inter-column prediction.

## Pinned source

The accepted path pins and validates:

- official UCI API metadata: 9,576 bytes, SHA-256
  `82b91c5ac61d01dadb53299d9be559f748c7e22904a6e4c08e313627d57e50b1`;
- official UCI CC BY 4.0 dataset page: 206,466 bytes, SHA-256
  `7181bb85f212ff0dec63b47c15ec17ca5f8f4ca742cbe6316b3a641fc882402e`;
- official ZIP archive: 218,381,995 bytes, SHA-256
  `aab991a970e58210de853bb8078ce0e63abb4d9412fdc5c79792dae3d8e1721a`;
  and
- `MetroPT3(AirCompressor).csv`: 218,300,507 bytes, SHA-256
  `db30ccb4ea402e3c8bf2c99db06e288d4f2a772f6928f9dbe26a920d69793e24`.

The CSV has exactly 1,516,948 observations and the pinned 17-column header.

## Accepted material

- 8 natural sensor-timeline samples;
- 1,516,948 uint8 values per sample;
- 12,135,584 primary values/bytes total;
- both binary states present in every signal;
- 254–64,580 transitions per signal;
- longest runs from 466 to 287,973 observations;
- eight unique payload hashes; and
- zlib-9 ratios from approximately 0.00128 to 0.02027.

The extremely low ratios are genuine operational structure: long steady
equipment states punctuated by sparse switching and pulse events.

## Verification, license, and safety

The accepted-path build reparses all 1,516,948 CSV rows and enforces exact
source spellings, distributions, transition counts, longest runs, and output
hashes. Verification independently repeats the source parse and compares every
emitted byte while rejecting stale or extra outputs.

The official UCI dataset page provides CC BY 4.0 rights evidence. UCI records
the source as non-sensitive industrial equipment telemetry. No timestamps,
locations, maintenance narrative, people, or personal data are emitted.
