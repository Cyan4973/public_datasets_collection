# LoRaIQ (EPFL) SF10 over-the-air LoRa frames, SigMF cf32_le I/Q

Native complex-float32 baseband I/Q recordings from the EPFL LoRaIQ dataset
(Tapparel and Burg, Zenodo record 17708397, version 1.0.0, CC BY 4.0). Four
USRP-2920 remote radio heads on EPFL campus rooftops recorded LoRa uplink
frames sent from a UAV. Each SigMF recording (`<n>.sigmf-data` +
`<n>.sigmf-meta`) holds exactly one detected frame plus surrounding channel
noise. One recording becomes one sample, bytes unchanged.

## Scope

- Radio configuration, pinned: SF10, CR 4/5, BW 250 kHz, 500 ksps,
  862.5 MHz (all `drone_los` / `drone_nlos` rows of `dataset.csv`:
  41,229 frames, one per file). The SF7 / BW 125 kHz / 250 ksps
  `pedestrian_nlos` sessions have a different sample rate and occupancy, so
  they are excluded.
- 16 drone sessions (2025-09-11 to 2025-10-07) x RRH 1-4 = 64 strata. Within
  each stratum, 4 evenly spaced recordings → **256 samples, 358,499,128 bytes,
  ~89.6 M float32 values** (median ~240k values = ~120k complex samples).
- The four 2025-09-18 sessions used a longer payload (129 B instead of 21 B).
  Their frames are 307,712 samples and their files ~2.75 MB, against
  ~0.96 MB elsewhere. The PHY and receiver chain are identical: it is the
  same regime with longer frames (64 of the 256 samples).

## Access path

`sigmfs.zip` is a 49.7 GB ZIP64 archive, so the recipe never downloads it
whole. `scripts/discover.py` (run via `discover.sh`; documentation only, not
part of the acceptance path) reads the ZIP64 EOCD and the 17.3 MB central
directory and pins, for every selected recording, the exact byte range from
the `.sigmf-data` local header through the end of the adjacent
`.sigmf-meta` member, plus both members' CRC32 and sizes (`selection.tsv`).

`download.sh`:
1. validates the Zenodo record JSON (id, title, version 1.0.0, license
   `cc-by-4.0`, sizes and MD5s of `sigmfs.zip` and `dataset.csv`);
2. fetches `dataset.csv` (18,306,157 B, md5 `b92831a0…`);
3. range-fetches the 256 member pairs (319,698,270 B in total). Each one is
   checked before it is kept: HTTP 206 with the exact `Content-Range`, local
   headers parsed with their own name and extra lengths (the local extra
   field is 28 B against 24 B in the central directory), raw-DEFLATE inflate
   ending exactly at the member boundary, and size/CRC32 equal to the pinned
   values. The SigMF metadata must give `cf32_le`, 500000 sps, 862.5, one
   channel, and a `core:sha512` that matches the data. The single annotation
   must give sf=10, cr=1, bandwidth 250000, the right file, and an off-grid
   value check.

`build.sh` re-inflates each local range and cross-checks the annotation
against `dataset.csv`. It writes
`samples/<id>/loraiq_sf10_iq_cf32/<session>_<rrh>_<n>.f32` and
`index/<id>/samples.jsonl`, whose rows add session, RRH, area type, SNR,
frame offset and length, source sha512, and the stored-float32 min/max.

`verify.sh` re-derives every sample with a separate parser and checks:
- byte identity with the inflated member, plus the SigMF sha512;
- index fields and stored min/max;
- finiteness, non-constant I and Q, and the width-honesty thresholds;
- manifest totals and realized scope (16 sessions, 4 RRHs, LOS and NLOS).

## Width honesty

The USRP-2920 streams sc16 over the wire, but these recordings come out of
the capture software's scaling and filtering. On real members, 0–0.001% of
values fall on the 1/32768 grid, 97–99% of float32 values are unique, and
mantissa trailing zeros fall off geometrically, so the full 23-bit mantissa
is in use. Build and verify reject any sample with more than 1% of values on
the grid or fewer than 50% unique values. Amplitudes are small (about ±0.01).

## Expected footprint

- network: ~338 MB (record JSON + CSV + ranges)
- downloads: ~338 MB
- samples: 358.5 MB
