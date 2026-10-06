# DANDI:000020 Patch-seq current-clamp membrane potential float32 development

## Outcome

Accepted `dandi_000020_patchseq_current_clamp_f32`. It was accepted on 2026-10-05 after one repair cycle.

The family holds complete whole-cell current-clamp sweeps from the Allen Institute's Patch-seq recordings of mouse visual-cortex neurons, mostly GABAergic interneurons. Each sample is one NWB `CurrentClampSeries` sweep: the neuron's membrane potential in mV, sampled at 50 kHz while one stimulus protocol ran. The protocols are test pulse, long and short square steps, ramps, chirp, noise and rheobase searches. The values are the producer's own float32 words, emitted bit for bit.

It is the first intracellular electrophysiology family in the corpus. The nearest neighbours are:
- `dandi_001076_zebrafish_calcium_fluorescence_f32`: optical calcium fluorescence at about 0.9 Hz;
- scalp EEG f32 and CTF MEG i32;
- extracellular recordings: Open Ephys i16 and Kilosort templates f32.

**Cycle 1 repair.** The first judge requested four changes:
1. Account for 44 X7Ramp sweeps that contain one interior run of MIES unacquired zero fill each.
2. Rewrite the width-honesty text, which wrongly claimed fully populated mantissas.
3. Correct a stale "no DANDI source" novelty claim.
4. Correct the distinct-value statistics.

The builder did all four without changing the selection or the payload.

## Source and rights

- **Source:** DANDI Archive dandiset 000020, published version 0.210913.1639, DOI 10.48324/dandi.000020/0.210913.1639. It holds 4,435 NWB assets from 1,040 donors, 141,856,436,428 bytes, served from anonymous S3 at `dandiarchive.s3.amazonaws.com`.
- **Pinned metadata:** `dandiset.yaml` is 3,119 bytes, SHA-256 `c0667d27…7897`. `assets.yaml` is 11,176,113 bytes, SHA-256 `65ef568e…a8fe`.
- **Downloads:** 16 NWB blobs, 521,558,599 bytes, each verified against its `dandi:sha2-256`.
- **License:** CC BY 4.0. The pinned `dandiset.yaml` declares `license: - spdx:CC-BY-4.0` and `access: - status: dandi:OpenAccess`, and every asset is `dandi:OpenAccess`. The live DANDI API version record agrees (status Valid).
- **Subjects:** house mouse (in-vitro slices). There is no human or personal data.

## Shape and conversion

**Selection.**
- Donors are sorted by numeric id and restricted to ids ≥ 732,239,848. This is the gain-0.05 window: 522 donors.
- 16 donors are taken at ranks `round(i*521/15)`, and the first NWB path is used for each.
- `download.sh` re-derives `sources.tsv` from the pinned `assets.yaml` and requires a byte-identical match.

**Decode.**
- A pure-stdlib HDF5 reader handles superblock v0, v1 object headers with continuations, symbol-table groups, attributes with vlen strings in the global heap, and a v1 chunk B-tree. Each chunk is zlib-inflated and unshuffled with element size 4.
- Sweeps are selected by `neurodata_type == "CurrentClampSeries"`, never by name.
- Each sweep must have unit `volts`, conversion float32(0.001), rate 50,000 Hz and gain float32(0.05).
- 289 VoltageClampSeries are excluded. No CurrentClampSeries was excluded for gain, rate, unit, length, constancy or NaN.

**Missing values.**
- *Trailing fill:* the trailing MIES unacquired run (+0.0 in every case) is trimmed and recorded per sample. This affected 271 sweeps and 59,029,871 of 171,305,500 stored values.
- *Interior fill:* 44 X7Ramp sweeps contain one interior run each of 960–1,983 exact zeros, 62,033 values in total, after the ramp's spike-triggered stop. They are kept in place inside the natural record and listed in the index as `interior_fill_runs`. Build and verify allow such runs only in X7Ramp sweeps, only once per sweep, and only up to 2% of a sweep. The fill counts are pinned.
- *Isolated zeros:* the 36 isolated exact zeros are genuine ADC code 0.

**Width.**
- Every word equals `float32(k / (3200 × float32(0.05)))` for an integer ITC-18 code k in [-16,768, 8,549]: a 1/160 mV lattice carrying about 14.6 bits of code information.
- The low byte takes 5 values.
- float32 is the archive's native stored type and the codes are not stored, so the bytes are kept as is. This follows the `kollmeyer_panasonic18650pf_drive_cycle_voltage_f64` precedent.

## Accepted output

- Source files used: 16 of 16 (16 donors, one neuron each), with 33–105 sweeps per neuron.
- Primary samples: 736.
- Primary values: 112,275,629.
- Primary bytes: 449,102,516.
- Sample length: minimum 7,650 values, median 54,650, maximum 1,180,000.
- Value range: -104.80 to +53.43 mV. The median of per-sample medians is -69.0 mV.
- Distinct values per sample: 174 to 11,816.
- Stimulus mix by sample count: X5SP_Search 201, X2LP_Search 100, X1PS_SubThresh 86, X7Ramp 73, X4PS_SupraThresh 71, X3LP_Rheo 55, X6SP_Rheo 55, C2SSTRIPLE 44, C1SQCAPCHK 25, C2NSD 15, C2CHIRP 11.
- Stimulus mix by bytes: X7Ramp 158.7 MB is the largest.
- Interior fill: 44 samples from 14 donors, 62,033 values, at most 0.913% of a sweep.
- Aggregate SHA-256 over samples in index order: `c0e5fda2f6674ec41a987907331a9b32ec5466264b36b37ce9cf1ca822be1515`.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/dandi_000020_patchseq_current_clamp_f32` passed with no warnings.
- **verify.sh:** I ran it myself (1:13.6). It reproduced the aggregate SHA and all pins: 736 samples, 449,102,516 bytes, 44 fill samples and 62,033 fill values.
- **Download:** the driver's download log shows 16 blobs verified, 521,558,599 bytes. build.sh reads only local files.
- **Lattice scan:** I scanned all 112,275,629 words independently in `/tmp/autocollect/dandi_000020_patchseq_current_clamp_f32/scan.py`. None is off the exact lattice rule. 22,449,239 words differ from the correctly rounded k/160, and they are exactly the low-byte-153 class. The low-byte histogram has 5 near-equal classes.
- **Fill runs:** my own groupby run scan matches the index fill runs exactly. All 44 are in X7Ramp_DA_0.
- **Other flat or duplicate content:** no constant run of a non-zero value is longer than 38. There are no duplicate payloads and no shared 4096-value heads.
- **Large jumps:** steps above 15 mV occur only at the fill boundaries, plus one spike upstroke.
- **Tamper tests:** in memory, verify's `independent_profile` rejected fill hidden from the index, fill injected into an X1PS sweep, and one word moved one ulp off the lattice. It accepted the real samples.
- **Self-test:** the builder's synthetic self-test passes against the current scripts.
- **Rights:** the pinned `dandiset.yaml` SHA matches. The live DANDI API returns CC-BY-4.0, OpenAccess and status Valid. The credential grep found nothing.
- **Novelty:** `novelty.py` with the dandiset URL and patch-clamp terms found no intracellular material locally, in the registry, in the ledger or downstream. The only other hits are same-host DANDI recipes, which hold different quantities.
- **Cosmetic nits, left as they are:** README "Realized output" says trimmed tails run "213 to about 1.5M values". The measured maximum is 1,106,067, and the median of 142,059 and total of 59,029,871 are correct. README "Width honesty" ends with "16-bit-information signal", while the measured code span is about 14.6 bits. Neither affects the payload or the checks.
