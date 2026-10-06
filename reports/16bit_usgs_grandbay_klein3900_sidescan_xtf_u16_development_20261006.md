# USGS Grand Bay Klein side-scan XTF backscatter uint16 development

## Outcome

Accepted `usgs_grandbay_klein3900_sidescan_xtf_u16`. It holds raw side-scan sonar ping backscatter from 24 complete Klein SonarPro XTF recording files of the USGS 2015 Grand Bay (Mississippi/Alabama) survey, field activity 2015-315-FA, project 15CCT03.

It is the first raw seafloor side-scan family in the corpus. The nearest local acoustic families are different instruments and processes:
- `zenodo_polarfront_ek60_power_i16`: water-column echosounder power.
- `noaa_wcsd_em302_water_column_i8`: multibeam water column.

The earlier `usgs_sidescan_sonar_tiff_u8/u16` attempts were processed mosaics with dead URLs and remain blocked.

Accepted after one repair cycle. The first judgment found that the documented array geometry was wrong ("sample 0 at nadir on both sides"). The repair corrected the manifest, README and index metadata, and added a verify check pinning the orientation. Sample bytes were unchanged (identical sha256s).

## Source and rights

- Source: Locker, S.D., Forde, A.S., and Smith, C.G., 2018, USGS data release, https://doi.org/10.5066/P9374DKQ
- Archive: `https://coastal.er.usgs.gov/data-release/doi-P9374DKQ/data/2015-315-FA_xtf.zip`
  - 9,843,630,446 bytes, Last-Modified 2018-10-01.
  - ZIP64 central directory at offset 9,843,618,372: 11,976 bytes, 145 entries (143 `.xtf`), SHA-256 `1c82077476a90a00184a574b4ef7199dffd522394073e352dae21b7091974247`.
- FGDC metadata: `GrandBay_2015-315-FA_metadata.txt`, 32,601 bytes, SHA-256 `36736ed67024c1130c5ec8affef67c9d9756e44a0eb67d530a32480d5897f770`.
- License: U.S. Government public domain.
  - FGDC text: "Access_Constraints: None. These data are held in the public domain. Use_Constraints: Public domain data from the U.S. Government are freely redistributable with proper metadata and source attribution." Resource_Description lists `*.xtf`.
  - The usgs.gov release page is marked "CC0 1.0 Universal".

## Shape and conversion

- Each natural record is one complete SonarPro XTF recording file. Every one of the 143 files is:
  - a 1,024-byte header;
  - then N pairs of one 832-byte HeaderType-108 Klein navigation/status record and one 16,768-byte HeaderType-0 sonar ping.
- Each sonar ping is a 256-byte ping header plus, for port (channel 0) and starboard (channel 1), a 64-byte channel header and 4096 little-endian uint16 samples (CHANINFO BytesPerSample=2).
- The emitted sample is ping-major `[pings, 2, 4096]` uint16 LE:
  - The channel arrays are copied verbatim, with no scaling, gain or slant correction, and no reordering.
  - Port is stored far range → nadir, and starboard nadir → far range, so each 8192-value row is one continuous across-track line.
  - The first 7 port and last 7 starboard samples are structural zeros in every ping (0.17% of values). They are kept and pinned by verify.
- Selection, cap-limited because the source holds 18.21 GB of XTF:
  - Keep files with 1000 ≤ N < 2700 pings, N = (uncompressed − 1024) / 17600, which is exact for all 143 members. That gives 25 files.
  - Drop the one file whose pings use frequency field 500. That leaves 24 files on 6 of 7 survey days.
  - The result is pinned with ZIP offsets, sizes and CRC32 in `sources.tsv`.
- Only the exact member byte ranges are fetched.
- Documented caveats:
  - The band favours shorter recordings.
  - The header SonarName 'Klein 3000' with frequency codes 100/500 differs from the FGDC 'Klein 3900, 455 kHz used'. Selection relies only on header values.
  - All files come from a single survey.

## Accepted output

- Source files in archive: 143. In band: 25. Selected: 24.
- Pings: 47,882 (1,005–2,697 per file, 0.1333 s per ping).
- Primary samples: 24.
- Primary values: 392,249,344.
- Primary bytes: 784,498,688.
- Minimum sample: 8,232,960 values (1,005 pings).
- Median sample: 17,600,512 values (2,148.5 pings).
- Maximum sample: 22,093,824 values (2,697 pings).
- Value range: 0 to 4,685. Per-file max 4,359–4,685; 3,753–4,508 distinct values per file.
- Zero fraction: 0.25%–2.7% per file, and 10.3% in `15CCT03_SSS_150528222700` (natural weak backscatter late in the recording).
- Bytes transferred: 464,297,806. Extracted XTF on disk: 842,747,776.

## Judge checks

- `gate.py`: PASS, no warnings.
- `verify.sh`, run by the judge: PASS in 33 s.
  - Independent re-walk of all 24 CRC-checked members, byte-identical samples, min/max/sha256 and totals recomputed.
  - `far_range_padding_ok pings_checked=47882`.
- Bytes, from struct/array inspection of 7 samples:
  - Heavy-tailed amplitudes (q50 13–185, q99 407–1,839), uniform low bits, no histogram gaps below 1,500, zero duplicate pings.
  - Adjacent pings are more similar than distant ones.
- Orientation, from per-index medians recomputed by the judge: port[0:7]=0, a far-range noise floor, seafloor rising toward port[~4031–4064], then near-zero at port[4090–4095]. stbd[0:16] is water column, the first return is at stbd[16–64], and stbd[4089:]=0. The first returns mirror each other around nadir, as documented.
- Homogeneity: all 47,882 pings × 2 channels share one channel-header configuration (slant 100 m, duration 0.13333, frequency code 100, gains 0, bandwidth 0, 4096 samples).
- Selection: re-derived from the local central-directory tail. All 143 members have whole ping pairs, the band holds 25, and the only one excluded from `sources.tsv` is the frequency-500 file.
- Rights: FGDC public-domain text (with `*.xtf`) read from the pinned file; CC0 marking confirmed on the usgs.gov page. No credentials; no personal data.
- Novelty: `novelty.py --url` on the XTF zip and the DOI matches only this recipe. `--terms` sidescan/xtf/klein/sonar match only blocked mosaic attempts. Downstream has nothing comparable.
