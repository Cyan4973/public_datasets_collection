# OOI CE04OSPS AC-S spectral counts uint16 development

## Outcome

Accepted `ooi_ce04osps_optaa_acs_spectral_counts_u16`. The recipe holds native uint16 raw per-wavelength detector counts from the WET Labs (Sea-Bird) AC-S hyperspectral absorption/attenuation meter (OOI designator OPTAAD105, serial 128). The instrument rides the OOI Cabled Endurance Array Oregon Offshore shallow profiler (CE04OSPS-SF01B, 0-200 m).

This is the corpus's first in-situ ocean-optics family. It is distinct from the accepted `ooi_ce02shbp_vel3d_adv_amplitude_correlation_u8`, which comes from the same archive but is a different instrument and quantity (uint8 acoustic amplitude and correlation). It is also distinct from the lab and airborne hyperspectral imaging cubes. Measured zlsim breadth is OK: the nearest family is downstream `venere_nir_hsi_detector_u16` at distance 0.0829.

## Source and rights

- Source: the OOI raw-data archive, `https://rawdata.oceanobservatories.org/files/CE04OSPS/SF01B/OPTAAD105/`. Access is anonymous HTTPS through nginx directory listings.
- Files: 33 daily port-agent files (`OPTAAD105_10.33.10.202_2101_2019MMDDT072x_UTC.dat`), 811,779,335 bytes in total. Each is pinned in `sources.tsv` by size, ETag and Last-Modified. OOI publishes no checksums, so download.sh computes a SHA-256 per file and build and verify re-check it.
- Selection: every 5th day from 2019-01-01 to 2019-06-10, taken from 154 eligible complete files (07:20-21:44 UTC, 23-25 MB). Target 2019-01-31 (a 43 MB merged file) and 2019-02-01 (a partial restart) were replaced by 2019-02-02. The window ends before the 2019-06-14..25 outage, after which a different unit (serial 221, 88 wavelengths) appears.
- License: OOI Data Use Policy 1102-00010 v2-00, section 4.1. It is a broad written grant to use, create derivative works, publish, distribute, disseminate, transfer or copy OOI data. The User Terms 1102-00020 add an NSF/OOI acknowledgement. Policy PDF sha256 is `52dc5db1709f3a264eec678fa8e71a107d3209b83f5ee7999ea1bf11d8b990d2`. It uses the same LicenseRef as the accepted VEL3D recipe.

## Shape and conversion

1. Port-agent frames (`a3 9d 7a`, type, length, XOR checksum, NTP timestamp) are walked contiguously to EOF, and every frame must be XOR-valid. Type-1 payloads are concatenated into the serial stream.
2. AC-S packets are located by the `ff 00 ff 00` registration. A packet is accepted when:
   - its record length is 704;
   - `sum(bytes[0:704]) & 0xffff` equals the stored big-endian checksum;
   - its pad byte is 0;
   - no registration occurs inside bytes [4, 704).

   After an accepted packet the scan resumes at +707.
3. Every accepted packet must carry packet type 5, reserved 1, meter 0x53, serial 128 and N = 84; any deviation fails the day.
4. Each packet's 84 × 4 BE uint16 spectral block (c_ref, a_ref, c_sig, a_sig per wavelength, in native order) is byte-swapped to little-endian. Sample shape is `[packets, 84, 4]`. Headers (dark counts, pressure, temperatures, elapsed time), checksums and text banners are not emitted.

The natural record is one daily port-agent file, the archive's file unit, which matches the VEL3D precedent. Each file holds the AC-S's two daily power-on windows, about 1 hour each at about 3.7 Hz.

About 8% of packet candidates are rejected each day (2,323 to 2,553). These are upstream-truncated packets: each begins at the start of a port-agent frame (usually an unusually large 272-byte frame), and the next registration follows 470-510 bytes later instead of 707. A further 5 to 18 per day are false registrations with a wrong length field.

## Accepted output

- Samples: 33 (one per day)
- Primary values: 307,414,800
- Primary bytes: 614,829,600
- Accepted packets per day: 27,593 to 27,820; accept fraction 0.915 to 0.923
- Sample size: 9,271,248 to 9,347,520 values; median 9,315,600
- Value range: 14 to 31,436 counts. Per-channel distinct values per day: 12,209 to 26,448. Per-channel mode share: at most 0.0020
- Series: `acs_spectral_counts_u16` (primary, native_numeric, uint16 little-endian)

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/ooi_ce04osps_optaa_acs_spectral_counts_u16` passed with no warnings.
- **Verify:** I ran `bash staging/ooi_ce04osps_optaa_acs_spectral_counts_u16/verify.sh` myself. It passed: the independent deframer and scanner re-derived all 33 samples byte-for-byte, and the totals match the manifest.
- **Build is local-only:** build.sh reads only `.data/downloads` and re-checks size and SHA-256. Grep found no network calls or credentials in build, verify or the Python scripts.
- **Bytes:** I read 4 samples with stdlib `array('H')`.
  - Mean spectra are smooth and monotone across all 84 wavelengths (for example, 2019-03-02 c_ref runs 662 → peak about 25,250 near wl55 → 8,093).
  - Signal falls below reference at the red end, consistent with seawater absorption.
  - Blue-end signal drifts slowly over the deployment.
  - There are zero duplicate and zero consecutive-identical packets.
  - Median packet-to-packet |delta| at wl40 is 10-17 counts.
  - Low values are isolated: on 2019-04-16 only 2 packets have wl0 c_sig below 100.
- **Truncation claim:** on the raw 2019-03-02 file, all 2,484 checksum failures start at frame offset 0, and the next registration follows 470-510 bytes later. The 100 '705-byte' gaps after good packets are false `ff00ff00` matches (checksum low byte 0xff), skipped by the +707 resume, so no real packets are lost.
- **Profile structure:** on 2019-04-16 the elapsed-time resets give 2 power-on segments, each 3,768 s long with about 13.9k packets.
- **Rights:** I re-fetched the policy PDF (sha256 unchanged), extracted its text with stdlib zlib, and confirmed the section 4.1 grant word for word.
- **Novelty:** `novelty.py --url/--terms` finds no AC-S, OPTAA or spectrophotometer family locally, in the registry or downstream. `--type/--instrument/--archive` returns 0/0/0. The vocabulary has no in-situ optics class. I label the recipe `new_quantity` rather than `new_modality`, because spectral detector-count cubes already exist (venere u16, Cassini VIMS downstream).
