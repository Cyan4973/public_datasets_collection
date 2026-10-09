# HUTUBS measured head-related impulse response float64 development

## Outcome

Accepted `hutubs_measured_hrir_f64`. Each sample is the native float64 measured head-related impulse response (HRIR) set of one subject in the HUTUBS HRTF database (Audio Communication Group, TU Berlin, with Huawei and Sennheiser). The recipe covers all 96 measured subjects.

This is the first head-related transfer material in the corpus, and the first acoustic impulse-response material at 64 bits. The existing impulse-response families are room responses: `openslr_rirs_noises_pcm16` (16-bit), `aalto_arni_room_impulse_response_f32` (32-bit), and downstream `measured_room_impulse_response_i16`. Those are long and reverberant. HRIRs are short (5.8 ms) anechoic responses on a direction × ear grid, carrying interaural time and level differences and pinna notches. Novelty kind: `new_source`. The card claimed `new_modality`, but acoustic impulse responses already exist at other widths. Measured breadth (zlsim): OK. The nearest family is `nasa_pds_gravity_harmonics_f64:gravity_sine_snm_f64` at distance 0.0832.

## Source and rights

- Source files: `https://sofacoustics.org/data/database/hutubs/pp{1..96}_HRIRs_measured.sofa`, the SOFA (AES69) community mirror of the canonical deposit.
- Canonical deposit: DepositOnce, "The HUTUBS head-related transfer function (HRTF) database", DOI 10.14279/depositonce-8487 (handle 11303/9429), issued 2019.
- Download: 96 SOFA files, 159,182,969 bytes, all sha256-pinned in `files.tsv`. Also `Documentation.pdf` (1,707,195 bytes, sha256 `cb52311e…71a4`) and the item page.
- License: CC BY 4.0. The DepositOnce item metadata carries `dc.rights.uri = https://creativecommons.org/licenses/by/4.0/`. Every SOFA file carries the global attribute `License = 'cc-by 4.0 (https://creativecommons.org/licenses/by/4.0/)'` with `DatabaseName = 'HUTUBS'`, so the grant is attached to the exact decoded objects. download.sh checks both; build.sh checks the per-file attributes.
- Privacy: subjects appear only as `pp1..pp96`. The deposit includes the depositor's privacy and consent declaration. Only acoustic responses are collected; head meshes, anthropometry and headphone responses are not downloaded.

## Shape and conversion

- Natural record: one subject's `ppN_HRIRs_measured.sofa`. A sample is that file's `Data.IR` array, shape [M=440 directions, R=2 ears, N=256 taps], in C order.
- Storage: netCDF-4/HDF5 (superblock v2, dense root links and attributes). `Data.IR` is `H5T_IEEE_F64LE`, stored as one chunk with shuffle(8)+deflate.
- Decoder: the pure-stdlib `h5lite.py`, identical in logic to the accepted cmip6/geoschem copies, with lookup3 metadata checksums verified. It inflates the chunk, undoes the HDF5 byte shuffle, and writes the stored 8-byte patterns unchanged.
- Guards: build requires the pinned global attributes, exact f64 LE datatype bytes, shape, single chunk, filter pipeline, 44.1 kHz rate and a byte-identical `SourcePosition` grid across all files.
- Missing-value policy (download, build and verify): NaN or infinity, |x| ≥ 1000 (netCDF fill), all-zero or constant (direction, ear) rows, fewer than 100,000 distinct values per subject, and duplicate samples are all fatal. None occur. The exact zeros at taps 0 and 255 are window edges and are kept.
- Excluded: `ppN_HRIRs_simulated.sofa`, BEM simulations on a 1730-point grid, which are a different generation process.

## Accepted output

- Primary samples: 96 (subjects 1..96, the full measured population)
- Values per sample: 225,280 (1,802,240 bytes); median 225,280
- Primary values: 21,626,880
- Primary bytes: 173,015,040
- Value range: -3.356814139462828 to 2.687951651821605
- Distinct bit patterns per sample: 223,522 in every subject (all nonzero values plus +0.0 and -0.0)
- Zeros per sample: 1,760 (taps 0 and 255 only)
- float32-exact fraction: 0.78125% (the zeros only)
- Shared grid sha256: `3c163d85ec7f5563ab07a5b74c8f4fe47734a66e612310dd09ec0385d928efc4`
- Data.Delay: [0, 0] for all subjects
- Flagged subjects: pp1 and pp96 are the FABIAN dummy head; pp22 and pp88 are one human measured twice. All four are kept as separate measurements, with `subject_note` in the index.

## Judge checks

- `python3 tools/autocollect/gate.py staging/hutubs_measured_hrir_f64`: PASS, no warnings.
- `bash staging/hutubs_measured_hrir_f64/verify.sh`: selftest ok, then verify ok (96 samples, 173,015,040 bytes).
- Independent decode: for pp1, pp37 and pp96 I scanned the raw SOFA bytes for zlib streams that inflate to exactly 1,802,240 bytes, without h5lite. Each file has exactly one such stream, at offset 41498, and after my own unshuffle it equals the emitted sample byte for byte.
- Width honesty: mantissa trailing-zero counts are geometric (about 40% with tz=0) and low-byte entropy is about 7.956 bits per sample. This is full-precision f64, not widened f32 or a fixed lattice.
- Physics, pp37 against the decoded SourcePosition (19 elevation rings from -90° to 90°, radius 1.47 m):
  - az 90°: onsets L18 / R47, which is 29 taps or 0.66 ms of ITD; ILD +18.9 dB.
  - az 270°: ILD -20.0 dB.
  - az 0° and 180°: equal onsets, ILD about 0 dB.
- Frontal-row peak at taps 31–38 in all 96 subjects.
- Near-duplicates: cross-subject correlation is -0.22 to 0.52 for unrelated pairs, 0.48 for the FABIAN repeat and 0.69 for the human repeat. The only bit patterns shared between subjects are ±0.
- Rights:
  - In the saved DepositOnce page, the HUTUBS item block (handle 11303/9429, correct dc.title) has the CC BY 4.0 dc.rights.uri.
  - A WebFetch of the live page confirms "Creative Commons Attribution (CC BY)" with DOI 10.14279/depositonce-8487.
  - `strings` on pp1, pp50 and pp96 shows the cc-by 4.0 License attribute and HUTUBS.
  - The Documentation.pdf license sentence could not be extracted with stdlib tools; it is not needed.
- No credentials in any script. build.sh reads local files only.
- Novelty:
  - `novelty.py` with the URL and the terms HUTUBS, HRTF, HRIR, sofa, sofacoustics, head-related, depositonce and binaural matches only this staging recipe and its ledger row.
  - The `--type`, `--instrument` and `--archive` lookups each return 0.
  - The vocabulary has no acoustic family at 64-bit.
- Accepted caveats:
  - The compression ratio is low (1.149) because the low mantissa bytes are near random. This is normal for processed f64 measurements.
  - The DepositOnce license check depends on the page's server-rendered metadata. If the rendering changes, download.sh fails rather than passing silently.
