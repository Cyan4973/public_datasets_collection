# NOAA Ship Rainier EM2040 seabed-image backscatter int16 development

## Outcome

Accepted `noaa_dcdb_rainier_em2040_seabed_image_i16`. It collects native signed-int16 Kongsberg EM2040 seabed-image (beam snippet) backscatter in 0.1 dB steps. The values come from the 'Y' (0x59, "Seabed image data 89") datagrams of raw `.all` survey-line files. NOAA Survey Launch 2802 (RA5) of NOAA Ship Rainier logged the files on 2023-04-30, during project RICHARD2023L4 (Kanton Island, Phoenix Islands, about 2.8 S 171.7 W).

This family is new material for the corpus:
- `noaa_wcsd_em302_water_column_i8` holds full range-time water-column amplitudes from a different sonar (EM302, int8, 0.5 dB).
- `usgs_grandbay_klein3900_sidescan_xtf_u16` holds linear towed-fish sidescan counts.
- `zenodo_polarfront_ek60_power_i16` holds single-beam log-power profiles.

This recipe collects the multibeam seabed-image product instead: short per-beam snippets around the bottom detection, with the sonar's real-time TVG and BSN/BSO backscatter normalisation applied.

## Source and rights

- Bucket: `s3://noaa-dcdb-bathymetry-pds`, read anonymously over HTTPS. It is NOAA NODD on AWS and not requester-pays.
- Folder: `mb/ships/rainier/RICHARD2023L4/multibeam/data/version1/MB/em2040/`. It holds 36 raw `*_2802.all.mb58` files, 8,172,258,772 bytes in total. The `.mb58` suffix is MB-System's id for the unmodified Kongsberg `.all` stream.
- Collected: the 20 smallest raw files, 2,442,068,200 bytes. Each is pinned by size and S3 ETag, recomputed locally. All 20 also match the upstream BagIt `metadata/manifest-md5.txt` of the cruise package.
- License: the AWS Open Data registry entry for the bucket names the whole bucket ARN as its resource and states: "NOAA data disseminated through NODD are open to the public and can be used as desired ... NOAA requests attribution for the use or dissemination of unaltered NOAA data." Endorsement may not be implied.
- Provenance: the data are a U.S. Government NOAA hydrographic survey. The cruise metadata lists "Kongsberg EM2040 .all files collected from NOAA Survey Launch 2802 (RA5) EM2040".

## Shape and conversion

Each natural record is one raw `.all` survey-line file. A sample concatenates the int16 sample block of every Y datagram in file order.

- Each ping has 400 beams. Each beam contributes Ns samples: mostly 3–5 in the 30.6 kHz mode, and up to about 1,200 in the deeper modes.
- Within a ping, the beams follow the datagram's sorting direction: -1 on port beams and +1 on starboard beams. A ping's block therefore runs across-track from port to starboard.
- The 36-byte header, the 6-byte beam entries, the zero pad byte, ETX and the checksum are removed. Nothing is rescaled, clipped or filled.
- Every datagram is checked for length, STX, ETX, the 16-bit byte-sum checksum and model 2040. Every Y datagram is also checked for serial 40129, 400 beams and the length identity: header + 6·N + 2·ΣNs + pad + 3.
- No file had an unframed or resync span.
- The auxiliary `em2040_beam_sample_count_u16` series holds the per-beam Ns. It reshapes a sample into ping × beam snippets and does not count toward acceptance.

Three sampling-frequency modes occur: 30,637.3 Hz, 20,424.8 Hz and 9,077.7 Hz. 15 files are single-mode 30.6 kHz, 4 are mixed, and 0035 is single-mode 9.08 kHz. Unit, lattice and normalisation are the same in all modes.

## Accepted output

- Source files: 20 of 36 (2,442,068,200 bytes)
- Y pings: 109,671 (× 400 beams)
- Primary samples: 20
- Primary values: 173,387,341
- Primary bytes: 346,774,682
- Minimum sample: 488,169 values (0030)
- Median sample: 6,376,584 values
- Maximum sample: 16,533,505 values (0022)
- Value range: -1235..+1066 (-123.5..+106.6 dB)
- Distinct values per file: 927–1,797
- -32768 count: 0
- Zeros per file: 175–5,766
- Auxiliary Ns bytes: 87,736,800

## Judge checks

- **Gate:** `gate.py` passes with no warnings.
- **Verify:** `verify.sh`, run by the judge, passes in 32 s. Its independent reader re-derives all 20 primary and auxiliary samples byte for byte and recomputes min/max/distinct/zero counts, sha256 and the manifest totals.
- **Upstream integrity:** the judge fetched the cruise BagIt `manifest-md5.txt`. MD5s of all 20 local files match it (20 of 20).
- **Independent decode:** the judge's own struct parser reproduces the stored 0004, 0031 and 0035 samples exactly.
- **Header fields:** Ns is never 0, and every centre sample number lies within Ns. TVG crossover is 10.0° and Tx beamwidth 1.0° on every checked ping.
- **Distributions:**
  - 30.6 kHz files: median about -18 to -21 dB, q01 about -50 dB, q99 about -3 dB.
  - Top value share is 0.42–0.65%.
  - No 64-value window repeats.
  - High bytes are 0xFF/0xFE/0x00, which is honest signed 16-bit use.
- **File 0035:** its hot tail (>+20 dB, 3.8% of the file, about 0.05% of the primary) is confined to the first 15% of its pings, mostly in the outer starboard beam deciles. The 9.08 kHz pings in 0031 and 0032 are not hot, so this is a transient in the logged field and not a separate mode regime. It is kept as logged.
- **Sorting direction:** tabulated per beam decile. Port beams are about 92–95% -1 and starboard beams about 99% +1, as the Kongsberg spec describes.
- **Novelty:**
  - `novelty.py --url` matches the same host only, on a different prefix and quantity (CSB tracks).
  - `--type`, `--instrument` and `--archive` each return 0.
  - zlsim rates breadth OK: nearest is downstream `chbmit_f7_t7_1d_var` at 0.0955 (loss 0.39%), mode share 0.57%.
- **Rights:** the registry YAML and the bucket readme were read directly. The scripts contain no credentials. Only acoustic amplitudes and Ns are emitted, so there is no personal data.

### Documentation notes for a follow-up edit

These do not affect the bytes, so they were not worth a repair cycle:

- Manifest `semantic_meaning` says "samples in range order". It should say the samples follow the datagram's per-beam sorting direction: across-track from port to starboard, with port beams highest-range first.
- The origin note says "no checksum manifest". An upstream BagIt `metadata/manifest-md5.txt` exists and matches all 20 pinned files.
- The README presents 0035 as a distinct acquisition regime. The offset is actually a transient in its first ~15% of pings.
