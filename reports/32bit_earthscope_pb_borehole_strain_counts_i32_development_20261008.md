# EarthScope PBO Gladwin borehole strainmeter gauge counts int32 development

## Outcome

Accepted `earthscope_pb_borehole_strain_counts_i32`. It holds complete UTC days of raw 1-sps gauge counts from the four horizontal capacitive extensometer gauges (LS1–LS4) of Plate Boundary Observatory Gladwin tensor borehole strainmeters (FDSN network `PB`, location `T0`).

This is the corpus's first borehole-strain family. It is not a new modality. The accepted `seismic_waveform_i32` already holds int32 counts from the same IRIS/EarthScope FDSN archive. This recipe adds a different instrument and physical quantity: a ~5e7-count bridge-ratio DC offset carrying smooth Earth-tide, barometric and relaxation signal, with occasional gauge resets. Novelty kind: `new_quantity`. The zlsim breadth verdict is OK.

## Source and rights

- Source: EarthScope FDSN web services (`service.earthscope.org/fdsnws`, formerly IRIS DMC). `dataselect/1` returns Steim2 miniSEED 2 with blockette 1000 and 512- or 4096-byte records; `station/1` provides the LS? channel inventory.
- Query plan: `plan.tsv` pins 154 (station, UTC day) rows, 2 days for each of 77 Gladwin stations, spread over 2008–2024. It was resolved once by `discover.sh` using crc32-derived candidate days and a 2-minute LS1 presence probe.
- Download: 154 files, 47,486,602 bytes, no empty responses. Local `mseed.sha256` checksums verify.
- License: CC BY 4.0. The GAGE Facility Data License page (June 12, 2025) says: "all data originating from EarthScope operated facilities will be licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0)". It names GAGE and SAGE, and miniSEED for attribution. `download.sh` re-fetches the page and fails if the statement is missing.
- Coverage of the exact objects: the PB network is `restrictedStatus="open"`. All 77 plan stations carry `alternateNetworkCodes=".EARTHSCOPE,_PBO,.UNRESTRICTED"`, so they are PBO facility stations rather than third-party contributions, and the page's carve-out for more restrictive contributor licenses does not apply.

## Shape and conversion

- Natural record: one gauge channel × one UTC day, the standard SDS day-volume unit. Each sample is 86,400 little-endian int32 values (345,600 bytes).
- Decoder: `scripts/mseed.py`, pure stdlib. It reads header byte order from BTIME, record length, encoding and word order from blockette 1000, applies blockette 1001 and the time correction, and decodes Steim2 frames, checking every record against X0 and Xn.
- A gauge-day is kept only if all of these hold:
  - all 86,400 one-second slots are filled exactly once (identical duplicates tolerated)
  - the records sit on the 1-s lattice
  - fill is at most 1% (864 values)
  - there are at least 16 distinct non-fill values

  Anything else skips the whole day; nothing is spliced.
- Channel filter: the inventory check restricts output to `GLADWIN TENSOR STRAINMETER` channels at 1 sps. Excluded: 20-sps BS? channels, RS*, auxiliary channels, and the LM laser strainmeters that share the LS? codes.
- Values are written unchanged: native int32 counts, with no widening, offset removal or remapping.
- Fill: the source's in-stream `999999` fill (hourly at fixed hh:30:xx slots, plus short outage runs) is kept verbatim and counted per sample in the index.

## Accepted output

- Gauge-days considered: 616. Complete: 608.
- Skipped: 8, logged in `ingest_stats.json`:
  - 5 with one missing second
  - 2 with no data
  - 1 at 90% fill
- Primary samples: 608, from 77 stations, covering every year 2008–2024 (8–56 samples per year).
- Primary values: 52,531,200. Primary bytes: 210,124,800. Every sample is 86,400 values.
- Fill: 21,411 `999999` values (0.041%). 121 samples have none; median 24 per sample; max 594.
- Per-sample non-fill minima: 1st percentile 35,576,590, median 50,002,735, 99th percentile 60,708,106, max 97,049,129. One source glitch value of −1 appears in B072 LS2 2023-07-06.
- Daily non-fill range: median 1,101 counts, 99th percentile 301,065.
- Max |step|: median 26, 99th percentile 269,968. These are gauge resets, kept as real instrument behaviour.
- Distinct values per sample: 43–51,413 (median 1,032).
- Aggregate decoded SHA-256: `489aad8cf6e5dcd02f997708107f275a5286d3eb1666fa8dfe81d8018ada7cbc`.
- zlsim: own compression ratio 8.25. Nearest family is `open_meteo_surface_pressure_f32` (distance 0.0691, loss 9.5%). Mode share is 1.84%.

## Judge checks

- `gate.py` passes with no warnings. I ran `verify.sh` myself: verify_ok, 608 samples, 210,124,800 bytes, 77 stations. It re-decodes every download and checks the output byte for byte. build.sh makes no network calls.
- Independent decode: I wrote a separate minimal Steim2 decoder and ran it on B004 2014-10-19 LS1 (512-byte records) and B072 2023-07-06 LS2 (mixed 512/4096-byte records). It reproduced both samples with 0 mismatches over 86,400 slots each, and found the 999999 values inside the archive records (B004 at slots 1821, 5421, … = hh:30:21).
- Bytes scan over all 608 samples:
  - no sha256 duplicates and no duplicated delta sequences
  - entropy of small deltas per sample: min 1.87, median 3.70, max 10.88 bits
  - 13 noisy or malfunctioning gauges (~2%) kept as real source behaviour
  - no sample stays inside the 16-bit range
- Rights: I read the downloaded license page text myself. A StationXML probe confirmed open status and `.EARTHSCOPE,_PBO` membership for all 77 stations. A grep of the scripts found no credentials.
- Novelty: `novelty.py --url` on each resource host plus `--terms` (strainmeter, Gladwin, borehole strain, GTSM, net=PB) found no strainmeter family locally, in the registry, the ledger or downstream. `--type/--instrument/--archive` each return 0 families. `tools/autocollect/README.md` confirms there is no per-host quota.
- Caveats: the four gauges of a station-day share the tidal signal; the 999999 fill spikes and gauge resets are kept as source behaviour. All three are documented in the README and in the per-sample index fields.
