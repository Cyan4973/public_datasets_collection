# OOI CE02SHBP VEL3D-C Nortek Vector ADV beam amplitude and correlation uint8 development

## Outcome

Accepted `ooi_ce02shbp_vel3d_adv_amplitude_correlation_u8` from the OOI raw-data archive. It holds native 8-bit per-beam acoustic return amplitude (counts) and Doppler beam correlation (%) from the Nortek Vector acoustic Doppler velocimeter (OOI class VEL3D-C, VEL3DC108) on the Cabled Endurance Array Oregon Shelf benthic experiment package (CE02SHBP-LJ01D, about 80 m). The instrument pings at 8 Hz with three receive beams.

This family is related to, but distinct from, the accepted `zenodo_adcp_pd0_backscatter_quality_u8`, which holds RDI ADCP PD0 echo intensity and correlation magnitude as depth-cell profiles. This recipe adds the same modality from a different instrument class: a single-volume point velocimeter at 8 Hz, sampled across a year-long seafloor deployment, from a new archive. Novelty kind: new content in an existing modality. The zlsim breadth gate measured both series as novel (verdict OK).

## Source and rights

- Source: `https://rawdata.oceanobservatories.org/files/CE02SHBP/LJ01D/VEL3DC108/`, one OOI port-agent stream file per UTC day (`VEL3DC108_10.33.14.7_2101_YYYYMMDDT0000_UTC.dat`, about 31.45 MB).
- Pinned objects: 57 day files, 1,792,629,992 bytes in total, listed in `sources.tsv` with exact URL, byte size, nginx ETag and Last-Modified.
  - OOI publishes no checksums. `download.sh` checks the ETag before fetching, checks the size, and validates each file semantically (port-agent framing, XOR checksums, timestamps inside the day).
  - It then records a self-computed SHA-256 in `download_plan.tsv`, which build and verify re-check.
- License: OOI Data Use Policy 1102-00010 v2-00, section 4.1. The policy PDF's SHA-256 is `52dc5db1709f3a264eec678fa8e71a107d3209b83f5ee7999ea1bf11d8b990d2`.
  - It grants the right to use OOI data "for any legal and non-prohibited purpose whatsoever ... to access, link to and use, create derivative works, publish, distribute, disseminate, transfer, or copy".
  - Section 2 defines OOI data to include data from instruments connected to the OOI system, which covers raw instrument data.
  - The User Terms and Conditions 1102-00020 require acknowledging NSF and the WHOI OOI Program Office; this is carried in the manifest citation.
  - The grant is broad and written, with attribution, but it is not an SPDX license (`LicenseRef-OOI-Data-Use-Policy`).
- Safety: seafloor instrument telemetry; no personal data; anonymous HTTPS; no credentials.

## Shape and conversion

Each natural record is one complete UTC-day port-agent file. The decoder is pure standard-library Python:

1. **Port-agent frames.** It walks the frames from byte 0 to EOF. Each frame has sync `a3 9d 7a`, a type byte, a big-endian length, an XOR checksum and an NTP timestamp. Every frame must be XOR-valid and contiguous, and the timestamps must fall inside the UTC day.
2. **Reassembly.** The type-1 payloads are concatenated into the instrument stream.
3. **Nortek scan.** Packets are kept only if they pass the Nortek checksum `(0xB58C + Σ LE words) & 0xFFFF`.
4. **Output.** From each Velocity Data packet (`a5 10`, 24 bytes), AmpB1..B3 (bytes 16-18) and CorrB1..B3 (bytes 19-21) are copied unchanged. Each day and series is written beam-planar as `[beam1][beam2][beam3]` raw uint8, shape `[3, n_records]`.

Velocities, pressure, System Data and port-agent framing are not emitted.

**Deployment window and homogeneity.** All days come from the deployment of 2025-08-28 to 2026-08-08. The instrument was swapped on 2026-08-09, and the previous deployment reports status 0x53; both are excluded. Nortek configuration packets never appear in the archived streams, so identity is enforced per day from Vector System Data:

- status byte 0x63 in at least 99.9% of packets;
- median heading 128-140°, pitch -3..7° and roll -3..6°.

**Day selection.** Days are 2025-09-01 + 6k (k = 0..56). The one exception is 2026-02-11, which replaces 2026-02-10 because that file switches to text `<OOI-TS>` framing at 20:17:31 UTC.

**Per-day guards, applied in both build and verify:**

- 690,000-692,000 velocity records;
- at most 0.01% checksum-failed velocity candidates;
- at most 0.1% unparsed stream bytes;
- at most 20 gaps in the record counter;
- every beam has at least 8 distinct values and no single value above a 75% share.

The 75% cap was loosened from 50% because clear-water days sit at the amplitude noise floor. The worst case is beam 3 on 2026-07-04 at 53.6%, with 56 distinct values.

## Accepted output

- Days decoded: 57, each with 691,200-691,202 velocity records and 86,400-86,401 System Data packets.
- Unparsed bytes, checksum failures and counter gaps: 0 on every day.
- Status byte 0x63: 100% of packets on every day.
- Realized orientation: median heading 131.5-135.8°, pitch 0.0-4.0°, roll -0.5-2.9°.

| series | unit | samples | bytes | range |
|---|---|---|---|---|
| `vel3d_beam_amplitude_u8` | counts | 57 | 118,195,383 | 78-206 |
| `vel3d_beam_correlation_u8` | percent | 57 | 118,195,383 | 0-100 |

- Primary samples: 114
- Primary values and bytes: 236,390,766
- Sample size: 2,073,600-2,073,606 bytes (3 × 691,200-691,202), median 2,073,603 values
- Breadth (zlsim, verdict OK):
  - Amplitude: own compression ratio 1.975; nearest is Statlog Landsat NIR at distance 0.0634 with 8.4% loss.
  - Correlation: own compression ratio 1.689; nearest is downstream `census_pums_person_age_u8` at distance 0.0529 with 0.0% loss. This is just outside the 0.05 threshold and is the weaker breadth claim of the two.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/<id>` passed with no warnings (114 samples, 236,390,766 bytes, median 2,073,603 values).
- **Verify:** I ran `bash staging/<id>/verify.sh` myself. It exited 0 with `verify_ok` (57/57 days per series), re-deriving every sample with the separate decoder. `build.sh` reads only `.data/downloads` after a SHA-256 re-check.
- **Independent decode:** I wrote a separate `struct` decoder that walks one frame at a time; each frame carries exactly one Nortek packet. On 2026-07-04 it reproduced both samples byte for byte. The decoded packet fields are coherent: pressure 81,218 mm, which matches the about 80 m site and confirms the Velocity Data byte layout.
- **Value distributions:**
  - Amplitude has beam-specific noise floors at about 78, 84 and 87 counts, rising to 206; lag-1 deltas cluster at 0/±1.
  - Correlation spans 0-100 with 101 distinct values; value 0 is 0.007% and 100 is 0.0002%, so there is no fill.
  - Daily correlation modes range from 34% to 98% with water clarity.
  - The 53.6% noise-floor day holds the floor at 44-61% in every 3-hour block, so it is a physical clear-water floor and not an outage.
  - All 114 sample hashes are unique, and the driver raised no fill warnings.
- **Scope:** the `sources.tsv` lattice matches 2025-09-01 + 6k exactly, apart from the documented 2026-02-10 → 2026-02-11 swap.
- **Rights:** I fetched the policy PDF and its SHA-256 matches the pinned value. I read section 4.1 of the policy and the attribution clause of the Terms myself. No script contains credentials.
- **Novelty:** `novelty.py` with the URL and the terms Nortek, VEL3D, CE02SHBP, OOI and oceanobservatories found no accepted, registry or downstream match. Same-type families are the RDI ADCP PD0 u8, EK60 and EM302 water-column families, with no same instrument line or archive. Labelled `new_content_same_modality` because acoustic-Doppler beam echo intensity and correlation already exist in u8 via the ADCP family.
