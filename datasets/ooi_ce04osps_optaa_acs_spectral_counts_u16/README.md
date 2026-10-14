# ooi_ce04osps_optaa_acs_spectral_counts_u16

Raw per-wavelength detector counts from the WET Labs (Sea-Bird) AC-S
hyperspectral absorption/attenuation meter (OOI designator OPTAAD105, serial
128) on the OOI Cabled Endurance Array Oregon Offshore shallow profiler
(CE04OSPS-SF01B, 0-200 m water column off Oregon). One uint16 sample per
daily raw port-agent file, 33 files across one deployment window
(2019-01-01 .. 2019-06-13).

## Source and license

- Archive: <https://rawdata.oceanobservatories.org/files/CE04OSPS/SF01B/OPTAAD105/>
  (anonymous HTTPS, nginx directory listings). Files are named
  `OPTAAD105_10.33.10.202_2101_YYYYMMDDTHHMM_UTC.dat` and hold one profiler
  day's serial stream (07:20-21:44 UTC, ~24.6 MB).
- License: OOI Data Use Policy 1102-00010 (section 4.1 grants use, derivative
  works, redistribution) plus the NSF/OOI acknowledgement of the User Terms
  1102-00020; same terms as the accepted
  `ooi_ce02shbp_vel3d_adv_amplitude_correlation_u8`. Policy PDF sha256
  `52dc5db1709f3a264eec678fa8e71a107d3209b83f5ee7999ea1bf11d8b990d2`.

## Pinned selection

`discover.sh` (metadata only) fetched the six 2019-01..06 listings, applied
`scripts/select_days.py` and HEAD-pinned size, ETag and Last-Modified into
`sources.tsv` (33 files, 811,779,335 bytes):

- eligible: start time T0720/T0721, listing date = file date, listing time
  21:4x, listed size 23-25M (complete files; 154 in the window);
- targets 2019-01-01 + 5k days, an ineligible target replaced by the next
  eligible unused day (01-31 is a 43 MB merged file and 02-01 a partial
  restart, so 02-02 is used);
- window end: probing 2019-06-28 shows a different unit (serial 221,
  88 wavelengths, 736-byte records) after the 2019-06-14 .. 06-25 outage, so
  nothing after 2019-06-13 is eligible. Serial 128 / N = 84 was confirmed on
  2019-01-02, 01-31, 03-15, 05-24 and 06-01 by range probes, and the build
  enforces it on every accepted packet.

## Decoding

1. **Port-agent frames**: `a3 9d 7a`, type, length u16 BE (incl. 16-byte
   header), XOR checksum u16 BE, NTP timestamp u64 BE. Every frame must be
   XOR-valid and contiguous to EOF; type-1 payloads are concatenated (AC-S
   packets straddle frames, as in the VEL3D recipe).
2. **AC-S packets** (layout per the OOI mi-instrument driver
   `mi/instrument/wetlabs/ac_s/ooicore/driver.py`): registration
   `ff 00 ff 00`; record length u16 BE at +4 (= 32 + 8N = 704); packet type
   (5) +6; reserved (1) +7; meter type (0x53) +8; serial +9..+11 (128);
   7 header u16 (dark counts, pressure, temperatures) +12; elapsed ms u32
   +26; N at +31 (84); then N x (c_ref, a_ref, c_sig, a_sig) u16 BE at +32;
   checksum u16 BE = `sum(bytes[0:704]) & 0xffff` at +704; pad byte 0 at +706.
   The checksum excludes the pad byte.
3. A candidate is **accepted** when the length is 704, the checksum matches,
   the pad is 0, and no `ff00ff00` occurs inside bytes [4, 704). The scan then
   resumes at +707.

### Why ~0-20% of packets are rejected

The scout's 64 KB probe found 52/67 checksum-valid packets. Re-probing
256 KB of 2019-06-01 gave 291 accepted out of 321 candidates. Every rejected
candidate is truncated in the archived stream: the next registration starts
478-499 bytes later instead of 707. In the port-agent framing, each truncated
packet starts at the beginning of an unusually large 272-byte frame (typical
frames are 8-248 bytes). A ~215-byte frame follows, then a ~208 ms
timestamp gap, and the next frame opens with a fresh registration. So the
tail (~220 bytes) was lost upstream of the archive, between the instrument and
the port agent. It is not a wrong checksum span: the remaining packets match
`sum(bytes[0:L])` exactly. The OOI driver uses the same rule. Rates seen
per probed hour: 2019-01-02 18%, 03-15 20%, 06-01 9%, 01-31 and 05-24 ~0%.

With ~3,000 rejected candidates per day, a 16-bit checksum would let a
spliced packet through about once per 65,536 tries. The no-internal-
registration rule rejects such splices outright. The zero-pad and
header-identity checks are further guards, and any identity deviation fails
the day rather than passing silently.

## Output

- Series `acs_spectral_counts_u16` (primary, native uint16, little-endian),
  one file per day: `samples/<id>/acs_spectral_counts_u16/YYYYMMDD.bin`.
- Layout: packet-major, shape `[packets, 84, 4]`. Within a packet, the
  wavelengths come in instrument order, each with the native channel
  interleave `c_ref, a_ref, c_sig, a_sig`. Only the spectral block is kept;
  headers (dark counts, temperatures, pressure, elapsed time) are dropped.
- Realized (build 2026-10-14): 33 samples, 614,829,600 bytes,
  307,414,800 values. 27,593-27,820 accepted packets per day (~18.6 MB per
  sample); accept fraction 0.915-0.923 on every day (rejections are almost
  all checksum failures of upstream-truncated packets, plus 5-18 per day
  `ff00ff00` false registrations with a wrong length field). Values span
  14..31,436 counts; every channel has 14k-26k distinct values per day with
  mode share < 0.2%. Day-mean spectra are smooth across wavelength, and the
  reference and signal counts track each other (e.g. 2019-03-02, first
  2,000 packets: wl0 ~[669, 682, 554, 472], wl40 ~[19688, 19433, 20912,
  23509], wl83 ~[8136, 7767, 5466, 6295]).
- Per-day statistics (rejection reasons, accept fraction, per-channel
  min/max/distinct/mode share) go to `filtered/<id>/ingest_stats.json`.

## Scripts

- `discover.sh`: how `sources.tsv` was resolved (listings plus HEAD only).
- `download.sh`: ETag-checked, resumable curl fetches. Each file then runs
  `optaa.py check-file` (framing, timestamps, packet yield, identity), and
  failures are deleted. Writes `download_plan.tsv` with SHA-256 values.
- `build.sh`: `optaa.py selftest` (synthetic port-agent and AC-S stream with
  a truncated packet, a corrupt packet, text banners and a forced
  checksum-colliding splice), then `optaa.py build`.
- `verify.sh`: `verify_optaa.py`, an independent deframer and scanner that
  re-derives every sample byte-for-byte. It checks index fields, manifest
  totals, the deployment window and identity, and per-channel degeneracy
  (>= 64 distinct values, mode share <= 50%).
