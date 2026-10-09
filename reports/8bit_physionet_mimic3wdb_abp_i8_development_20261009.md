# MIMIC-III Waveform Database ABP int8 development

## Outcome

Accepted `physionet_mimic3wdb_abp_i8` from the immutable PhysioNet MIMIC-III Waveform Database 1.0 release.

This is the first arterial blood pressure (ABP) family at any width, locally or downstream. Clinical bedside-monitor waveforms previously existed only at 16 bits: BIDMC PPG/respiration and CHARIS intracranial pressure. CHARIS reads its ABP channel for checksums but does not emit it. The existing 8-bit physiological families are surface biopotentials (MIT-BIH ECG, EMG), a different waveform. Novelty kind: new quantity in a known modality.

The recipe went through one repair cycle. The first build kept 53 segments. Two of them, 3013004_0158 and 3018045_0013, had no beat-synchronous pulse and used the full 8-bit range with WFDB invalid markers. A whole-segment monitor-range rule (-125..125) now excludes them.

## Source and rights

- Source: `https://physionet.org/files/mimic3wdb/1.0/`, version 1.0, published 2020-04-07, DOI 10.13026/c2607m.
- Files: 60 pinned segment `.hea` and format-80 `.dat` files.
  - Each is pinned by size and by the SHA-256 from the release `SHA256SUMS.txt`.
  - `RECORDS-adults` and `LICENSE.txt` are pinned the same way.
- Download: 688,090,604 B in total, of which 687,268,057 B are `.dat`.
- License: Open Data Commons Open Database License v1.0.
  - The project page states: "Access Policy: Anyone can access the files, as long as they conform to the terms of the specified license. License: Open Data Commons Open Database License v1.0".
  - The release `LICENSE.txt` is the ODbL text (SHA-256 `bcdfcd4f31c790e30fb645dc36414907172405897adff329ad379eed85d12017`).
  - ODbL is share-alike. Accepted ODbL precedent: OSM, taginfo, OpenFlights, NCLT.
- Safety:
  - The data are de-identified ICU waveforms, collected under IRB approval with consent waived.
  - Open access: no credentialing and no data use agreement.
  - Only ABP stored values are emitted. Base times, ICU location comments and layout headers never reach samples, index or stats; `verify.sh` greps for them.

## Shape and conversion

Each natural record is one WFDB waveform segment; one segment is taken per record (patient stay).

**Selection.** Author-time and pinned:
- walk `RECORDS-adults` in file order;
- in each record, take the first chronological segment that has:
  - at least 500,000 frames at 125 Hz;
  - all signals in format 80 in one `.dat`;
  - exactly one `ABP` signal at gain string `1.25(-100)/mmHg`, 8-bit ADC resolution, ADC zero 0;
- stop at 60 records (2,762 walked; all in directory `30/`).

Other ABP calibrations are different tick lattices and are not collected. These include `1.28(-109)` and format-16 `20.4733(307)`.

**Decode.**
- Read nsig and the ABP column index from each header.
- Take every nsig-th byte; emitted int8 = stored byte XOR 0x80, the WFDB digital value.
- Physical pressure is (value + 100) / 1.25 mmHg, in 0.8 mmHg steps.
- Every signal's 16-bit WFDB checksum and the ABP initial value are verified.
- No resampling, clipping, imputation or within-segment cutting.

**Keep rule.** Whole segments only. A segment is excluded if any of these holds:
- more than 10% of its values are -128;
- one code holds more than 25% of its values;
- fewer than 50% of its 60 s windows are pulsatile;
- it has fewer than 32 distinct codes;
- any value lies outside the monitor range -125..125.

The rule is pinned in `mimic_pins.py` and re-implemented in `mimic_verify.py` with a drift check.

**Saturation.** The monitor output saturates at codes ±125 (-20 / 180 mmHg). Saturated values, including pegged flush or sampling runs, are kept in place and counted.

## Accepted output

- Pinned segments: 60
- Excluded whole: 9
  - 3012395_0001, 3031663_0003, 3033264_0007 and 3043821_0010: a single pegged code holds more than 25% of values.
  - 3013395_0001: flat at about 28 mmHg, and outside the monitor range.
  - 3038577_0007: 16.6% invalid, and outside the monitor range.
  - 3042059_0028: 43% pulsatile windows.
  - 3013004_0158 and 3018045_0013: outside the monitor range, no cardiac pulse.
- Primary samples: 51
- Primary values: 195,628,953 int8 (195,628,953 bytes)
- Minimum sample: 526,888 values (70 min)
- Median sample: 2,068,767 values (4.6 h)
- Maximum sample: 19,575,000 values (43.5 h)
- Window classes: 25,940 pulsatile of 26,101 (99.4%), 104 flat, 41 low, 16 damped, 0 invalid
- Saturation:
  - code +125 holds 1,607,325 values (0.82%), at most 9.07% in 3001920_0037;
  - the longest +125 run is 88,847 frames (3009600_0002);
  - code -125 holds 48,881 values (0.025%).
- Distinct codes per sample: 185–251; largest mode share 12.5% (3042934_0005)
- Download overhead: 687,268,057 / 195,628,953 ≈ 3.5x
- Aggregate sample SHA-256: `bbdcf5e3a1cd4da00e63d2424707efbfca57648e29d5e2515ef5213815d3cb85`
- zlsim (driver, 51-sample build): OK. Own ratio 4.56; nearest feature distance 0.0799 (AlphaEarth i8). MIT-BIH MLII u8 is compression-close (loss 0.028) but at distance 0.11.
  - The README says zlsim was measured on the earlier 53-sample build. The driver's re-measurement gives the same distances, with mode share 0.040.

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **Verify:** I ran `verify.sh` myself: exit 0, 51/51 `ok` lines, and the aggregate SHA-256 matches. `build.sh` reads only `.data/downloads`. Build, verify, synth and pins contain no network code. `download.sh` contains no credentials.
- **Bytes:** I inspected all 51 samples with stdlib Python under `/tmp/autocollect/`.
  - MAP is 43–105 mmHg; median systolic/diastolic 85–162 / 34–72 mmHg. Excerpts show a textbook arterial pulse.
  - The ABP autocorrelation period matches the ECG lead in the same `.dat` frames in 344 of 348 excerpts, and every excerpt byte-matches its `.dat` column.
  - Zero deltas are balanced at even/odd and mod-3 positions, so there is no sample-and-hold.
  - No value outside -125..125 and no -128.
  - The saturation figures above were recomputed and match the README.
- **Documented totals:** recomputed from the pins and headers and all match: 237,094,260 frames, 687,268,057 `.dat` bytes, signal sets (PAP in 16, CVP in 1) and the excluded-segment diagnostics.
- **Rights:** I opened the saved landing page and the pinned `LICENSE.txt`.
- **Novelty:** `novelty.py` with URL/terms, `--type/--instrument/--archive` and `--vocabulary` found no ABP or MIMIC entry locally or downstream.
