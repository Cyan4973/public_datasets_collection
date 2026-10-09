# OOI CE02SHBP VEL3D-C Nortek Vector ADV beam amplitude and correlation (uint8)

Native 8-bit per-beam **acoustic return amplitude** (counts) and **Doppler beam
correlation** (%) from the Nortek Vector acoustic Doppler velocimeter (OOI class
VEL3D-C, reference designator CE02SHBP-LJ01D-06-VEL3DC108) on the Cabled
Endurance Array Oregon Shelf benthic experiment package, ~80 m deep. The
instrument pings at 8 Hz; each ping has 3 receive beams.

## Source

- Raw archive: <https://rawdata.oceanobservatories.org/files/CE02SHBP/LJ01D/VEL3DC108/>
  with one OOI port-agent stream file per UTC day
  (`VEL3DC108_10.33.14.7_2101_YYYYMMDDT0000_UTC.dat`, ~31.45 MB).
- `sources.tsv` pins 57 files: every 6th UTC day from 2025-09-01 to
  2026-08-03, with byte size, nginx ETag and Last-Modified from HEAD requests
  made 2026-10-09. Download total: 1,792,629,992 bytes.
- Exception: 2026-02-10 is replaced by 2026-02-11. The 2026-02-10 file
  (31,454,716 bytes, about 5 KB over a normal day) drops port-agent binary
  framing at byte 26,590,764 (20:17:31 UTC). From there it writes text
  `<OOI-TS ...Z TS>` / `<\OOI-TS>` delimiters around the Nortek packets, and
  the strict deframer rejects that. The day was not patched; a
  normal-size neighbour day replaces it.
- OOI publishes no checksums. `download.sh` checks the ETag before fetching,
  checks the size, validates each file semantically (`vel3d.py check-file`),
  and records a self-computed SHA-256 in `download_plan.tsv`. Build and verify
  re-check those hashes.

## License

OOI Data Use Policy 1102-00010 v2-00, section 4.1: "all OOI data will be made
publicly available, free of charge ... The User is granted the right to use OOI
data and web sites for any legal and non-prohibited purpose whatsoever ... --
to access, link to and use, create derivative works, publish, distribute,
disseminate, transfer, or copy." The User Terms and Conditions 1102-00020
require acknowledging NSF/OOI. This is a broad written grant with attribution,
not an SPDX license.

## Deployment window (homogeneity)

All selected days come from one VEL3D-C deployment:

- It starts with the post-turnaround restart files of 2025-08-28 16:12-16:55
  UTC. There is no port-agent restart file after that, and every day file
  through 2026-08-08 is a complete ~31.45 MB day.
- On **2026-08-09** the instrument changes: the System Data heading jumps from
  134.8 to 265 deg, battery reads 11.7 V instead of 11.5 V, and beam-2
  amplitude sticks at 71. Everything from that day on is excluded.
- The previous deployment (to 2025-08) reports status byte 0x53, heading about
  118 deg and different amplitude levels, so it is excluded too.
- The archived streams contain no Nortek configuration packets (0xA5 0x00,
  0x04 or 0x05), so the serial number cannot be read. Identity is instead
  enforced per day from Vector System Data (0xA5 0x11, 1 Hz):
  - the status byte (orientation, scaling and power-level bits) must be 0x63
    in at least 99.9% of packets;
  - median heading must be 128-140 deg, pitch -3..7 deg and roll -3..6 deg.

  Within the window, heading drifts 131.5 to 135.8 deg and pitch 0 to 4 deg
  in small steps, which looks like the frame settling on the seabed.

## Decode (pure stdlib)

1. **Port-agent frames.** Each frame is `a3 9d 7a`, a type byte, a 2-byte
   big-endian length (including the 16-byte header), a 2-byte checksum and an
   8-byte NTP timestamp.
   - The checksum is the XOR of all frame bytes with the checksum field
     zeroed. Every frame must pass it.
   - Frames must be contiguous from byte 0 to EOF.
   - The timestamps must fall inside the file's UTC day.
2. **Reassembly.** Type-1 payloads (data from instrument) are concatenated.
   Nortek packets straddle frame boundaries, so the scan runs on this stream.
3. **Nortek scan.** Keep checksum-valid packets, where the checksum is
   `(0xB58C + sum of LE uint16 words except the last) & 0xFFFF == last word`.
   - Velocity Data (`a5 10`) is a fixed 24 bytes: AmpB1..3 at bytes 16-18 and
     CorrB1..3 at bytes 19-21.
   - Other packets carry their size in words at bytes 2-3.
4. **Output.** For each day and series, write
   `[beam1 all records][beam2 all records][beam3 all records]` as raw uint8:
   - shape `[3, n_records]`, with n ≈ 691,201 per day;
   - one sample per UTC day per series;
   - path `samples/<id>/<series>/<YYYYMMDD>.bin`.

Per-day guards in both build and verify:

- 690,000-692,000 velocity records per day;
- checksum-failed velocity candidates at most 0.01%;
- unparsed bytes at most 0.1%;
- count-byte gaps at most 20;
- every beam has at least 8 distinct values and no value above a 75% share (clear-water days sit
  at the amplitude noise floor; the largest realized share is beam 3 of
  2026-07-04, value 90 at 53.6%, with 56 distinct values).

The probe day 2025-09-01 decoded 691,201 velocity and 86,400 system packets
with zero junk, zero checksum failures and zero count gaps.

`verify.sh` re-derives every sample with a separately written decoder. It
checks byte equality, index fields, manifest totals and the guards above.
`build.sh` first runs a synthetic self-test that covers:

- straddling packets;
- a corrupted packet;
- a partial packet;
- non-data frames;
- a corrupted port-agent checksum.

## Series

| series | unit | source field |
|---|---|---|
| `vel3d_beam_amplitude_u8` | counts | Velocity Data AmpB1..B3 |
| `vel3d_beam_correlation_u8` | percent (0-100) | Velocity Data CorrB1..B3 |

Realized output: 57 samples per series, 2,073,600-2,073,606 bytes each
(3 x 691,200-691,202 records), 118,195,383 bytes per series, 236,390,766
bytes total.

## Notes and risks

- **Breadth (zlsim gate, 2026-10-09, verdict OK).** The rule is redundant
  only if loss <= 0.03 AND distance <= 0.05 against one family.
  - Amplitude: own ratio 1.975. Nearest is Statlog Landsat NIR at distance
    0.0634 with 8.4% loss. The closest low-loss neighbour is RSTN SRS spectra
    at distance 0.079 with 1.2% loss.
  - Correlation: own ratio 1.689. Its nearest neighbour is borderline:
    downstream `census_pums_person_age_u8` at distance 0.0529 with 0.0% loss,
    just outside the 0.05 threshold. Next is Sentinel-1 coherence at 0.060
    with 2.5% loss. Correlation passes the gate, but it is the weaker
    breadth claim of the two series.
- **Correlation.** Correlation varies widely day to day (daily medians about 18-97%)
  with water clarity. That is the natural signal, not a fault.
