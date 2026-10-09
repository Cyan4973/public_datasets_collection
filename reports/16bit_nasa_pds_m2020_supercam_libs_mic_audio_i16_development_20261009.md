# Mars 2020 SuperCam microphone LIBS audio uint16 development

## Outcome

Accepted `nasa_pds_m2020_supercam_libs_mic_audio_i16` from the NASA PDS
Geosciences Node Mars 2020 SuperCam bundle.

This family is the first acoustic material recorded off Earth in the corpus.
The SuperCam microphone on the Perseverance mast records the shock waves of
laser-induced breakdown sparks, plus Martian wind and ambient noise, in the
~6 hPa CO2 atmosphere. Existing `pcm_audio` families are all terrestrial:
LibriSpeech, ESC-50, NSynth, FSDD, Asterisk, CirCor PCG, Rousettus bat calls,
MIMII valves and Chopin piano. The existing Mars recipes are imagery,
topography and radar. Novelty kind: new source within `pcm_audio`, not a new
modality.

## Source and rights

- Source: `https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_supercam/data_raw_audio/`
  (collection `urn:nasa:pds:mars2020_supercam:data_raw_audio`, v16.0, 13,420
  raw-audio products)
- Pinned selection: `sources.tsv` (634 products, SHA-256
  `3bea302314c546f8aba21d0f6757272166ebabe9ef085ab4883691f806252661`). For
  each product it pins the URL, size, MD5 from the bundle manifest, the SOUND
  header offset, and the SHA-256 of the primary and SOUND header blocks.
- Download: 396,984,960 bytes of whole FITS files, each MD5-checked
- Rights: NASA SMD Science Information Policy ("information produced from
  SMD-funded scientific research activities be made publicly available"). The
  bundle carries no license or restriction text. This is the same basis as the
  accepted `nasa_pds_mastcamz_raw_i16` and `nasa_pds_sharad_edr_raw_echo_i8`.
  SuperCam is a LANL/CNES instrument archived in NASA PDS.

## Shape and conversion

Each natural record is one raw-audio PDS4 FITS product. The HDUs are, in
order: primary, ODL LABEL, TIMELINE, MU_SOH, BU_SOH, LASERDATA, SOUND. The
final SOUND binary table holds 174,000 rows of `TFORM1 'I'`, `TZERO1 32768`,
the FITS convention for unsigned 16-bit data. The emitted value is the
physical ADC code (stored + 32768), written little-endian uint16. There is no
crop, resample or calibration, and one product yields one sample. The
instrument itself packs one ~60 ms window per laser shot into the table (the
laser fires at 3 Hz; shocks recur every ~6,000 samples). The recipe
concatenates nothing.

Only one configuration is kept: `MIC_SAMP=100000`, `MIC_DOWN=F`,
`MIC_SAMC=21`, `MIC_GAIN=2`, `MIC_DURA=1`, `HSS_NUMW=174000`, `LIBS_MIC=T`,
`LASDNS00=30`, `SCMDTYPE=9`. Gains 1 and 3 are excluded because gain changes
the amplitude scale.

Selection is deterministic:

1. Take the 12,220 products under 1 MB, sorted by file name (sol, then SCLK).
2. Split them into 800 equal windows.
3. In each window, take the first product that matches the configuration.

This resolved 634 windows. The other 166 held only gain-1, gain-3 or
other-length products. The gain-2 30-shot population (~6,700 products,
~2.3 GB of SOUND data) exceeds the 1 GB cap.

## Accepted output

- Primary samples: 634 (0 quality rejections)
- Values per sample: 174,000 (1.74 s at 100 kHz)
- Primary values: 110,316,000
- Primary bytes: 220,632,000
- Sols: 86-1857, 465 distinct
- Value range: 0-3654; per-sample mean 1871-1926
- Per-sample std (min/median/max): 16.05 / 27.63 / 228.66 counts
- Order-0 entropy per sample (min/median/max): 5.75 / 6.43 / 9.2 bits
- Max dominant-value fraction: 0.0615; median distinct values per sample: 537
- zlsim: OK. Nearest is `downstream:mitbih_v5_1d_var` at feature distance
  0.0488, but compression loss is 0.0551, so it is not compression-equivalent.

## Judge checks

- `gate.py`: PASS, no warnings.
- `verify.sh`, re-run by the judge: verified all 634 samples byte-for-byte
  with the independent parser (backward SOUND scan, sign-bit flip). Totals
  match the manifest.
- FITS structure: dumped the HDU headers of a product by hand. Keyword values
  and SOUND layout match the manifest. LASDSF00=3 Hz confirms per-shot windows
  rather than a continuous 1.74 s recording.
- Bytes (stdlib struct, all 634 samples):
  - No value above 4095, so the content is a 12-bit ADC in the native 16-bit
    container. No even-only samples; low bits are balanced.
  - Envelope autocorrelation gives a ~6,000-sample shot period.
  - The leading word of most recordings is a single +100 offset value, which
    is negligible.
  - Only one sample touches code 0 (2 values).
  - No repeated 2,000-value windows across 1,902 probes. Same-sol pairs
    correlate 0.09-0.61, which is synchronized shot timing, not duplication.
- Rights: opened the NASA SMD policy page and the bundle `readme.txt` and
  `bundle_supercam.xml`. Neither the readme nor the label has restriction
  text. The scripts contain no credentials.
- Novelty: ran `novelty.py --url`/`--terms`, `--vocabulary` and
  `--type/--instrument/--archive`. There are no SuperCam or Mars-audio hits
  locally, in the registry or downstream.
- Minor wording, no repair needed: the README cites an observed maximum of
  "~3,050" from the probe sample, while the realized maximum is 3,654. The
  `_i16` suffix on a uint16 series follows existing precedent
  (`dwd_radolan_rw_precip_i16`, `tcia_nsclc_radiomics_ct_i16`).
