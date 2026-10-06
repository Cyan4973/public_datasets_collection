# PhysioNet CHARIS intracranial pressure channel int16 development

## Outcome

Accepted `physionet_charis_icp_i16`: the complete 50 Hz intracranial pressure (ICP) channel of the 9 majority-ICP records of the PhysioNet CHARIS database 1.0.0. These are multi-day neuro-ICU recordings after traumatic or other acute brain injury. The recipe emits them as the publisher's WFDB format-16 stored values, little-endian int16, unchanged.

This is the first intracranial or arterial pressure waveform in the local or downstream corpus. The source host is shared with other PhysioNet recipes (BIDMC PPG/RESP, CirCor PCG, TPEHG EHG, GRABMyo sEMG, EIT, ECG, EEG), but none of them is a pressure-transducer channel.

The recipe took two repair cycles:
- **Cycle 1:**
  - excluded charis9 and charis10;
  - corrected the representation: the values are publisher auto-scaled stored values, not raw ADC codes;
  - added stretch and unused-code diagnostics.
- **Cycle 2:**
  - added an exact-integer lag-1 autocorrelation waveform test (r1 ≥ 0.5) to the plausible-ICP window class;
  - excluded charis8 and charis12 as majority non-ICP under that test.

## Source and rights

- Source: the anonymous PhysioNet open-data bucket `https://physionet-open.s3.amazonaws.com/charisdb/1.0.0/`, a mirror of `physionet.org/files/charisdb/1.0.0/` (published 2017-01-19).
- Pins:
  - SHA256SUMS.txt (2,083 B, `13a392e1…91da`);
  - RECORDS (108 B);
  - all 13 `.hea` headers;
  - the 9 kept `.dat` files (1,224,261,912 B), each pinned by size and SHA-256 and cross-checked against all 27 SHA256SUMS entries.
- Excluded records: charis8, 9, 10 and 12. Their `.dat` files (538,643,052 B) are not downloaded; their headers are still fetched and checked.
- License: Open Data Commons Attribution License v1.0 (ODC-By 1.0), open access with no credentialing.
  - The project page states: "Anyone can access the files, as long as they conform to the terms of the specified license. License Open Data Commons Attribution License v1.0".
  - The view-license page carries the ODC-By 1.0 text.
  - download.sh saves both pages and text-checks them.
- Attribution:
  - Kim N et al., J Clin Monit Comput 30:821 (2016);
  - dataset DOI 10.13026/C24G6F;
  - the standard PhysioNet citation.
- Safety: de-identified human clinical material.
  - Header comment lines (age, sex, diagnoses, outcome) are discarded on parse.
  - verify.sh fails if demographic or outcome text reaches the index or stats.
  - Only ICP stored values are emitted. ABP and ECG are read only to validate checksums.

## Shape and conversion

- Natural record: one patient recording's complete ICP channel, WFDB signal index 2 of the interleaved frame (ABP, ECG, ICP).
- Conversion: read each `.dat` as little-endian int16 frames, take every third value starting at index 2, and write the values unchanged.
  - There is no rescaling, gain or baseline conversion, filtering, clipping, inversion or segment removal.
  - Length equals the header nsamp, and every signal's 16-bit sum equals its header checksum.
- Representation: all 9 kept records were auto-scaled by the publisher to the full int16 range. Each has exactly one +32767 and one −32767, and no −32768.
  - The native monitor scale is 60.8182 codes/mmHg. Evidence: the excluded charis12's unscaled header and the ECG gains of 6081.5 and 6081.8 per mV.
  - Kept stretch r = gain / 60.8182 is 1.3193-1.6127, so 0.242-0.506 of the integer codes in the 0-40 mmHg band are unused.
  - The index records `stretch_vs_native` and `unused_code_fraction_0_40mmhg`.
- Content, over 68,017 60-s windows of the kept records:
  - 81.44% plausible ICP with a pressure waveform present;
  - 9.65% arterial pressure on the ICP input;
  - 6.49% pegged output;
  - 1.11% above 250 mmHg;
  - 0.79% ICP-band white noise;
  - 0.31% other high;
  - 0.14% flat;
  - 0.08% negative.
- Other content figures:
  - 14.09% of values lie outside −10..100 mmHg;
  - 121 wrap-like jumps;
  - every kept record is at least 52.1% plausible (minimum charis3).
  - These are descriptive only: nothing is cut inside a kept record.

## Accepted output

- Records in release: 13. Kept: 9 (charis1-7, 11, 13). Excluded: 4 (charis8 47.7%, charis12 38.2%, charis10 20.0%, charis9 8.6% plausible-ICP windows).
- Primary samples: 9
- Primary values: 204,043,652
- Primary bytes: 408,087,304
- Minimum sample: 7,199,999 values (charis4, 40 h)
- Median sample: 17,095,224 values (charis3, 95 h)
- Maximum sample: 67,499,794 values (charis2, 375 h)
- Distinct codes per record: 10,242-25,619
- Aggregate sample SHA-256 (`record:sha256` lines, canonical order): `e6248950384520292a76f076757129f3667509843d1ef249d368e6e0bab869ef`
- WFDB checksums: all 27 (9 records × ABP/ECG/ICP) match their headers.

## Judge checks

- **gate.py:** PASS with no warnings.
- **verify.sh:** re-run by the judge; exit 0 and the same aggregate SHA as the driver's rebuild. build.sh calls only local-file Python, with no network imports.
- **Independent decode:** a struct de-interleave of charis4 and charis6 is byte-identical to the sample files. The `.dat` SHA-256 matches SHA256SUMS.txt, and the ABP, ECG and ICP checksums match the headers.
- **Content probes:** charis1, 3, 7, 11 and 13 at 2/25/50/75/97% of each record.
  - ICP segments sit at 3-31 mmHg with cardiac periodicity of 70-120/min (autocorrelation peak r up to 0.91).
  - Pegged stretches (charis3 ~100.7 mmHg, charis13 ~186 mmHg) are low-amplitude noise with about 30-64 distinct codes per 500 samples, not constants.
  - Arterial-like stretches (charis7, charis11) sit at ~120-130 mmHg.
- **Degeneracy and duplicates:** the longest exact-constant run in any record is 9 samples, and no 3000-sample window repeats within or across records.
- **Wraps:** these are brief artifact spikes, e.g. in charis5: 1086, 11678, -24573, five samples near -22250, then back to ~1140.
- **Lattice:** a regular gap pattern, with the most common deltas being 0, ±3, ±4, ±7 and ±11. The used-code fraction matches 1/r: charis6 0.733 vs 0.739.
- **Rights:** the license statements were read from both saved HTML pages.
- **Leak check:** grepped the index, ingest_stats, download_inventory and build log for age, sex, outcome and diagnosis text. Nothing leaked.
- **Novelty:** `novelty.py` on both URLs with the terms charisdb, CHARIS, intracranial, ICP, arterial, blood pressure and ABP. It found no pressure-waveform family locally or downstream.
- **Cosmetic, non-blocking:**
  - some failure-path messages in charis_build.py and charis_verify.py still say "11 kept records";
  - the charis_download_check.py docstring lists only charis9 and charis10 as excluded.
