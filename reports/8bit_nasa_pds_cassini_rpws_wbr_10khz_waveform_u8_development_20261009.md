# Cassini RPWS WBR 10-kHz waveform uint8 development

## Outcome

Accepted `nasa_pds_cassini_rpws_wbr_10khz_waveform_u8`: uncalibrated 8-bit waveform data numbers from the Cassini Radio and Plasma Wave Science (RPWS) Wideband Receiver. The data are in the 10-kHz baseband mode (0.06-10.5 kHz, 36 us sampling) on the Ex electric dipole, recorded in Saturn orbit. These are the audio-band plasma-wave and radio-emission waveforms (chorus, hiss, electron-cyclotron harmonics, plasma-frequency tones, lightning whistlers, dust impacts).

This is the corpus's first space-plasma electric-field waveform family at any width. The broad 8-bit 1-D sensor-waveform modality already exists downstream (speech PCM, mu-law, MIT-BIH ECG, seismic), so the novelty is a new source and quantity, not a new modality. The measured breadth verdict is OK. The nearest family is downstream `mitbih_mlii_u8`, at statistical distance 0.0298 and compression loss 0.0349, just above the 0.03 redundancy threshold. The existing Cassini recipes are VIMS spectral cubes (i16) and RADAR BIDR SAR images (u8).

## Source and rights

- Source: NASA PDS Planetary Plasma Interactions Node, University of Iowa subnode, `https://space.physics.uiowa.edu/pds/CORPWS_nnnn/DATA/RPWS_WIDEBAND_FULL/`, data set `CO-V/E/J/S/SS-RPWS-2-REFDR-WBRFULL-V1.0`.
- Volumes: CORPWS_0040 + 18k for k = 0..11. CORPWS_0202 has no 10-kHz product in the size window, so 11 volumes contribute.
- Pinned bytes: 297,335,488 DAT + 522,796 LBL (297,858,284), plus 57,379 evidence bytes (WBFULLDS.CAT, RPWS_WBR_WFR_ROW_PREFIX.FMT and AAREADME.TXT, MD5-pinned).
- The server publishes no checksums. DATs are pinned by exact size plus a full label check and record walk, and their SHA-256 is recorded in `download_plan.tsv` at download time and re-checked by build and verify.
- License: NASA SMD open scientific data policy. The policy states that information produced from SMD-funded research is "made publicly available". The volume AAREADME imposes no restriction and only encourages acknowledging the PDS and the instrument PIs. This is the same basis as the accepted `nasa_pds_cassini_vims_qube_i16`, `nasa_pds_cassini_radar_bidr_sigma0_u8` and `nasa_pds_voyager_iss_saturn_raw_u8` recipes.

## Shape and conversion

Each natural record is one archived hourly WBR full-resolution product, `T<yyyyddd>_<hh>_10KHZ<n>_WBRFR.DAT`. It is a PDS3 fixed-length binary table: each record is a 32-byte big-endian row prefix followed by one AGC-ranged waveform capture, of which the first SAMPLES bytes are valid.

For every product the recipe:
- checks the detached label: WBRFULL, interval 0.000036, OFFSET -127.5, UNSIGNED_INTEGER, ITEM_BYTES 1, and RECORD_BYTES x FILE_RECORDS = file size;
- walks every record, requiring RECORD_BYTES (u16 at offset 12) to match the label and SAMPLES (u16 at offset 14) to fit within capacity;
- keeps records with FREQUENCY_BAND == 2, ANTENNA == 0 (Ex), the WBR validity bit (0x40) set and the TIMEOUT/SUSPECT bits (0x30) clear;
- concatenates the first SAMPLES bytes of each kept record in file order and writes them unchanged.

Fill bytes beyond SAMPLES, the row prefixes and the label text are never emitted.

Selection: in each volume, the 10-kHz baseband products (band token exactly `10KHZ`, which excludes 75KHZ, 5KHZ, 325KHZ and the frequency-translated HF products) with DAT size of 1-8 MB were sorted by product id and taken at 8 evenly spaced ranks. Three picks were replaced because their probe showed only Langmuir-probe or Ew records. The AGC gain (0-70 dB per capture) is not applied, since it is part of the instrument's native DN regime. Gaps between captures are not represented.

Record-length classes in the selection: 2080 bytes x71 products, 4128 x10, 6176 x4 and 8224 x3. SAMPLES varies below capacity in the larger classes, and the per-record value is used.

## Accepted output

- Pinned products: 88 (8 per volume x 11 volumes), 2004-314T19 to 2017-045T06
- Products excluded: 0
- Source records: 126,742; kept: 126,742 (all band 2 / Ex / unflagged)
- Primary samples: 88
- Primary values and bytes: 284,050,336
- Minimum sample: 947,472 values
- Median sample: 2,476,032 values (upper median; gate mean-of-middle 2,472,960)
- Maximum sample: 7,668,432 values
- Analog gain codes over kept records: 2: 1,439; 3: 25,407; 4: 73,568; 5: 15,445; 6: 5,507; 7: 5,376
- Mode share per sample: 1.9-11.2%; DN 0 + 255 at most 0.65%; all 256 DN levels used across the set
- Aggregate sample SHA-256: `7e18c94f74e3724ace033b054b9015e9d4f573ce11c7b687061f712e16cc7bde`
- Breadth (zlsim): OK; own ratio 2.83; nearest `mitbih_mlii_u8` 0.0298 / 0.0349, then `mitbih_v2_u8` 0.0449 / 0.035 and `mitbih_v1_u8` 0.0538 / 0.0203

## Judge checks

- `python3 tools/autocollect/gate.py staging/nasa_pds_cassini_rpws_wbr_10khz_waveform_u8`: PASS, no warnings.
- `bash staging/.../verify.sh` (re-run by the judge): `verify ok samples=88 excluded=0 bytes=284050336 median=2476032 volumes=11 dn_levels=256`. verify.py re-implements the record walk independently and byte-compares every sample.
- Confirmed against the evidence FMT the prefix layout and bit numbering (PDS START_BIT 1 = MSB): WBR = 0x40, TIMEOUT = 0x20, SUSPECT = 0x10, ANALOG_GAIN = low 3 bits, band code 2 = 10 kHz/36 us, antenna code 0 = Ex.
- Independent struct walk of all 126,742 records:
  - 0 duplicate captures (md5) within or across products, 0 constant captures, 21 captures with fewer than 8 distinct DN (quiet intervals);
  - all fill bytes past SAMPLES are zero and are not emitted.
- Byte inspection of 14 samples:
  - per-capture means of 129.4-130.6;
  - SD of 3-30 DN, tracking gain;
  - lag-1 autocorrelation of about 0.98 (oversampled waveform);
  - odd/even DN balance of about 0.50 (no widened codes);
  - code gaps only in the rare far tails;
  - order-0 entropy of 3.9-6.3 bits.
  The snippets show clean oscillations and one clipped large transient.
- Novelty: `novelty.py --url` for both resource URLs plus the terms returned only self-matches; the `--type`/`--instrument`/`--archive` query returned 0/0/0; the vocabulary and the 8-bit downstream list contain no plasma-wave family.
- Rights: fetched the NASA SMD policy page (public availability, no stated restrictions) and read the pinned AAREADME (acknowledgement request only). No credentials appear in any script.
- Natural record: one sample per archived hourly product follows accepted multi-record product precedents (SHARAD radargram products, Klein XTF recording files, BATSE daily files). Each capture alone clears the 1,000-value floor, so the concatenation is not floor-gaming.
- Minor documentation note, not blocking: the manifest resource `version` string lists CORPWS_0202, which contributes no products. `deterministic_notes` explains this.
