# EM302 multibeam water-column int8 development

## Outcome

Accepted `noaa_wcsd_em302_water_column_i8`. It holds native signed-int8 water-column backscatter amplitudes from the Kongsberg EM302 multibeam echosounder on NOAA Ship Okeanos Explorer, cruise EX1711 (Nov–Dec 2017). Each sample is one complete 288-beam ping.

This is the first multibeam water-column family in the corpus. Existing 8-bit sonar material is different in kind:
- `zenodo_polarfront_ek60_angles_i8`: single-beam split-beam angle codes.
- `zenodo_adcp_pd0_backscatter_quality_u8`: 4-beam ADCP echo-intensity counts.

Neither covers a 288-beam fan of TVG-corrected amplitudes, and neither comes from the NCEI archive.

## Source and rights

- **Source:** the NOAA NCEI Water-Column Sonar Data Archive, an anonymous public S3 bucket `s3://noaa-wcsd-pds` (us-east-1, not requester-pays).
- **Folder:** `data/raw/Okeanos_Explorer/EX1711/EM302/`, which holds 407 `.wcd` files (92.6 GB) uploaded 2021-03-06.
- **Pinned objects:** 15 whole objects, 357,457,606 bytes, each pinned by size and S3 ETag. Multipart ETags are recomputed locally over 8 MiB parts. The live listing is checked against the pins before any fetch.
- **License:** the AWS Open Data registry entry `ncei-wcsd-archive.yaml` says: "The data may be used and redistributed for free but is not intended for legal use, since it may contain inaccuracies", followed by a no-warranty disclaimer. These are U.S. Government (NOAA) observations.
- **Citation:** from the MD5-pinned cruise README: NOAA Office of Ocean Exploration and Research (2017), Water Column Sonar Data Collection (EX1711, EM302), NCEI, doi:10.7289/V5W957HS.

## Shape and conversion

Each `.wcd` file is a Kongsberg EM datagram stream. Every datagram in every file is checked for length, STX, ETX, the 16-bit byte-sum checksum and model 302, in download, build and verify.

**Ping assembly.** Water-column datagrams `k` (0x6B) are grouped by (date, time, ping counter). A ping is kept only when:
- all datagrams 1..Nd are present;
- the per-ping header fields agree across its datagrams;
- the beam total is exactly 288;
- beam pointing angles strictly decrease.

**Primary sample.** Each beam's Ns int8 amplitudes are concatenated in datagram and beam order and written unchanged, one file per ping. -128 is the native floor code and is kept.

**Auxiliary series.** Two alignment series per ping, 288 values each, excluded from the floors:
- per-beam sample counts (u16), which mark the beam boundaries of the ragged vector;
- pointing angles (i16, 0.01°).

**Fatal conditions:**
- serial ≠ 101;
- TVG ≠ 30/20;
- non-zero start range sample;
- inconsistent headers;
- interior partial pings;
- duplicate payloads.

**Homogeneity.** The EM302 switches depth mode automatically. Range sampling is 202.92, 295.16 or 541.13 Hz, with 8, 6 or 4 transmit sectors. That changes range resolution and swath geometry, not the quantity, unit, TVG law or lattice. The mode fields are kept per ping in the index.

## Accepted output

- **Source files:** 15 whole files, covering 14 survey days from 2017-11-30 to 2017-12-20.
- **Primary samples:** 1,953 complete pings, 26 to 348 per file.
- **Primary values and bytes:** 343,505,942.
- **Sample size:** min 86,916, median 115,350, max 549,808 values.
- **Modes (pings):**
  - 202.92 Hz with 8 sectors: 1,164
  - 295.16 Hz with 8 sectors: 428
  - 295.16 Hz with 6 sectors: 123
  - 541.13 Hz with 4 sectors: 238
- **Dropped pings:** 0 edge-partial and 0 blank. Every 'k' datagram belongs to an emitted ping.
- **Floor code -128:** 2,296,563 values (0.67%).
- **Amplitude range:** -128..127, with all 256 codes present. Each ping has 169 to 255 distinct levels.
- **Auxiliary:** 2 × 1,953 samples, 1,124,928 bytes per series.
- **Aggregate SHA-256** of the primary samples in index order: `a861ca568114ad4a530be30746c316b71b51f9e1139cc610e2ece19f98366136`.

## Judge checks

- **Gate:** `gate.py` passed with no warnings.
- **verify.sh:** I ran it twice; both exited 0. Its decoder is independent and imports only the pinned file table and the ETag helper.
- **Network and credentials:** build.sh reads only `.data/downloads`. Grep finds no network calls or credentials in build, verify or the Python scripts.
- **Download log:** the listing check passed (407 objects, 15 pins matching), as did the README MD5 and DOI check. Every file passed its ETag check and a full datagram scan.
- **Independent decode:** my own `struct` parse of one 6-datagram ping from file 0270 reproduced its sample byte for byte. For every file, the sum of Nd over emitted pings equals the 'k' datagram count. Every file ends exactly at EOF on an `i` datagram.
- **Physical plausibility:**
  - Outer/nadir Ns tracks 1/cos(angle): 3.27 against 3.24 at 72°.
  - The bottom echo peaks at about 85–90% of each beam.
  - Nadir depths of about 365, 780 and 1,160 m match the 541, 203 and 295 Hz modes.
  - Global percentiles: p25 -71, median -53, p95 +4, p99.9 +52.
- **Redundancy:**
  - Dual-swath pairs 0.02–0.08 s apart and full cycles match on only about 3% of bytes, with beam-aligned MAD of about 13 codes.
  - xz joint gain on a pair is 0.3%, so there are no near-duplicates.
  - xz compresses one ping to 0.73–0.77 of its size.
- **Per-mode distributions:** medians -68 to -48, p99.9 between 40 and 53, floor 0.6–1.9%. Same lattice, no regime break.
- **Rights:** I fetched `ncei-wcsd-archive.yaml` myself. The free use-and-redistribution statement covers ARN `noaa-wcsd-pds`.
- **Novelty:** `novelty.py` with the bucket URL and the terms EM302, wcd, multibeam, kongsberg, okeanos, water column, EX1711 and wcsd matches only this candidate. `pipeline/candidates.tsv` has no accepted sonar family at any width.
- **Minor README wording:** the README says the files "cover all three depth modes seen in the cruise". That is only verified for the selected files, where there are four sampling-frequency and sector combinations. It is descriptive, not a scope claim.
