# Zenodo MiniSEED native-int16 ground motion

- **Dataset ID:** `zenodo_miniseed_int16`
- **Date attempted:** 2026-08-19
- **Status:** blocked
- **Intended source:** permissively licensed, real nonhuman seismic or geophone
  ground-motion recordings using MiniSEED v2 encoding 1
- **Discovery log:** `.data/logs/zenodo_miniseed_int16/discover.latest.log`
- **Discovery evidence:** `.data/discovery/zenodo_miniseed_int16/summary.json`,
  `records.tsv`, `files.tsv`, and `probes.tsv`

## Intended value

Native signed-int16 MiniSEED would add a new geophysical waveform domain. Each
complete station/channel segment would be a natural sample, with the declared
MiniSEED word order converted to canonical little-endian only when necessary.

Encoding 1 is particularly attractive because MiniSEED v2 blockette 1000
declares the signed-int16 storage, word order, and record length explicitly,
allowing a small dependency-free decoder.

## Discovery performed

The license-first Zenodo discovery searched six MiniSEED, seismic, geophone,
earthquake, volcano, ambient-vibration, and ground-motion query variants over
three result pages each. It found:

- 372 unique records;
- 53 records passing permissive-license and real-geophysical-measurement
  metadata filters;
- 232 bounded direct or archive resources;
- 10 representative direct-file probes, capped per record to avoid one
  multi-file record consuming the budget;
- 30 bounded ZIP central-directory/member-prefix probes; and
- 12 bounded TAR or TAR.GZ member-prefix probes.

The parser validated MiniSEED v2 fixed headers, traversed blockettes to
blockette 1000, checked record length and payload geometry, and recorded
encoding, word order, sample rate, and stream identity.

## Why it is blocked

No probed MiniSEED record used encoding 1. Every valid MiniSEED payload used
one of:

- encoding 4: IEEE float32;
- encoding 5: IEEE float64;
- encoding 10: STEIM-1 compressed signed-int32; or
- encoding 11: STEIM-2 compressed signed-int32.

Representative examples included hour-split 100 Hz earthquake waveforms,
continuous Ridgecrest and Campi Flegrei station data, large multi-station ZIP
archives, and event-waveform TAR.GZ members. Their record headers parsed
cleanly, but none contained a native int16 record or mixed int16 segment.

STEIM's packed differences do not make its logical samples 16-bit; STEIM-1 and
STEIM-2 reconstruct signed 32-bit integers. Likewise, float32/float64 samples
must not be narrowed merely because some observed values might fit an int16
range. Promoting any candidate would therefore misclassify or lossily convert
the source representation.

## Retry condition

Do not repeat the broad Zenodo search. Retry only with an exact permissively
licensed real geophysical source already known to declare MiniSEED v2
blockette-1000 encoding 1, or another documented native signed-int16 waveform
format. The discovered encoding-4 records may be evaluated separately as a
float32 seismic family; they are not replacements for this blocked 16-bit ID.
