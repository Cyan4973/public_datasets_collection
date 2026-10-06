# Aalto Arni variable-acoustics room impulse responses (float32)

Measured room impulse responses (RIRs) from the variable-acoustics laboratory
"Arni" at the Aalto University Acoustics Lab (Espoo, Finland), published on
Zenodo as record [6985104](https://doi.org/10.5281/zenodo.6985104) under
CC-BY-4.0 (Prawda, Schlecht and Välimäki, 2022).

Arni's walls carry 55 panels that can each be switched between a reflective
(closed) and an absorptive (open) state. The authors measured 5,342 panel
configurations with one omnidirectional loudspeaker and five fixed
microphones, repeating each swept-sine measurement up to five times: 132,037
WAV files in total. Each file is a mono 44.1 kHz WAVE_FORMAT_IEEE_FLOAT
(32-bit) impulse response of 105,840 samples (2.4 s).

## What is collected

One sample per impulse-response WAV, holding the WAV `data` chunk as raw
little-endian float32 (105,840 values, 423,360 bytes):

- 53 absorption levels: numClosed = 0..55 reflective panels, excluding
  levels 11, 27 and 35 (see below);
- one configuration per level: the lowest global combination number
  (`numComb`) outside the special block 2..31 for which the first sweep
  exists for all five receivers and every one of those five members is at
  least 200,000 bytes compressed (see below);
- all five receivers (mic 1..5), first sweep only.

This gives 265 samples, 28,047,600 values and 112,190,400 bytes. Repeat sweeps
2..5 of the same configuration and receiver are excluded as near-duplicates.
The upstream authors discarded some sweeps because of non-stationary noise. If
a configuration lacks `sweep_1` for any receiver, the rule moves on to the
next `numComb`. In the pinned record this happens for numClosed 1 (seven
combinations skipped) and for numClosed 30 and 49 (one each).

### Why numComb 2..31 is excluded

Combination numbers run as follows:

- 0 = all reflective (the only option for numClosed 55);
- 1 = all absorptive (the only option for numClosed 0);
- 2..31 = 30 out-of-sequence special configurations spread over many levels;
- 32..86 = numClosed 54;
- 87..141 = numClosed 1;
- then 100 per level.

A first version of this recipe took the lowest numComb per level and so drew
14 levels from the special block. In four of those configurations several
receiver labels hold the same acoustic response. Over sample indices
[1500, 17884):

- numComb 5 (numClosed 11): mics 1-3 share one direct-sound arrival index
  and correlate at r >= 0.9998; mics 4-5 are distinct.
- numComb 7, 21 and 27 (numClosed 16, 27, 35): mics 1-3 share one arrival
  index at r >= 0.9997, and mics 4-5 share another at r >= 0.9995.

All other configurations peaked at |r| = 0.086. The whole special block is
therefore excluded. This moves 14 levels to the first regular combination of
their block:

8:2->742, 11:5->1042, 16:7->1545, 19:10->1842, 20:6->1942, 24:18->2342,
27:21->2642, 28:11->2742, 31:9->3042, 35:27->3442, 36:17->3542, 39:20->3842,
44:30->4342, 47:28->4642.

numClosed 16 lands on 1545 rather than its first regular combination 1542,
because of the compressed-size rule below. No new sweep_1 fallbacks are
needed.

### Why numClosed 11, 27 and 35 are excluded

The receiver-distinctness check below then failed on the first regular
configuration of three levels: numComb 1042 (numClosed 11), 2642 (27) and
3442 (35). The pattern is the one seen in the special block:

- mics 1-3 hold one response: r = 0.9999, with one direct-sound arrival index
  close to a normal mic-1 arrival.
- mics 4-5 hold a second response (r >= 0.9997) at an arrival typical of
  mic 2. numComb 1042 is the exception: its mic 5 is distinct.

The excluded special combinations 5, 21 and 27 belong to the same three
levels, which points to faulty recordings for these levels rather than
individual bad files.

Partial-range probes of further configurations inflated only the first
17,884 samples of each member. They found the same duplication at:

- numClosed 11: 1043, 1060, 1100, 1120 and the last configuration 1141;
- numClosed 27: 2643, 2660, 2700, 2720;
- numClosed 35: 3443, 3470, 3500, 3520.

Only the last configuration of levels 27 and 35 (2741, 3541) measured as
distinct. Rather than pick atypical end-of-block configurations by a
content-driven scan, the recipe excludes these three levels entirely
(`EXCLUDED_LEVELS` in `scripts/arni_zip.py`). Neighbouring levels 10/12, 26/28
and 34/36 cover the same reverberation range.

### Why int16-quantized members are excluded (compressed-size rule)

Four upstream members hold int16-quantized data written as float32. All are
numClosed 16, mic 5, sweep 1: numComb 1542, 1543, 1544 and 1594. The 1542
member, selected in the previous build, has:

- 100% of its 105,840 values on the 2^-15 lattice, i.e. integer multiples of
  1/32768;
- only 192 distinct codes, between -377 and 323;
- 86.5% of its values equal to -1/32768 (= -3.05e-5), and 5,113 exact zeros;
- a zlib ratio of 3.2%, against about 88-93% for genuine samples.

These members DEFLATE to 12.8-13.8 KB inside the archives. Every other one of
the 132,037 members is at least 342,676 B, and every selected genuine member is
at least 370,163 B. The selection therefore requires all five sweep_1
members of a configuration to be at least `MIN_COMPRESSED_BYTES = 200,000`
compressed bytes, a central-directory-only rule. This moves only numClosed 16,
from 1542 to 1545. Before pinning 1545, it was probed on all five mics over
the first 17,884 samples: no value on the int16 lattice, max pairwise |r|
0.055, and normal per-mic arrival indices.

### Receiver-distinctness check

For every selected configuration (53 in the current selection), compute the zero-lag Pearson correlation of
the five receivers' float32 samples over indices [1500, 17884): the direct
sound and early decay, about 34-406 ms. Take the maximum |r| over all 10
receiver pairs. It must be < 0.5, or the recipe fails. `download.sh` runs this
check (`arni_tool.py distinctness`). `verify.sh` runs a separately written
implementation that uses raw sums on the stored sample bytes. Both log each
configuration's max |r|. They also log, without failing, the largest
correlation between two configurations for the same receiver. That value can
be high, because neighbouring configurations that differ by one panel
legitimately sound alike.

Current output: all 53 configurations pass with max |r| <= 0.0863 (median
0.0597). The largest cross-configuration same-receiver |r| is 0.9715, for mic
4 between numClosed 54 (numComb 32) and 55 (numComb 0). Those two
configurations differ by a single panel.

### Float-lattice / degeneracy check

Each sample must have fewer than 1% of its values on the int16 lattice, where
x * 32768 is an integer, and at least 50,000 distinct float32 bit patterns. A
failure is fatal. The shared download/build path enforces this in
`arni_zip.float32_stats`, which `arni_tool.py extract`, `final-check` and
`build_samples.py` all call. `verify.sh` enforces it with a separate
implementation (`is_integer` on x * 32768 and a set of raw 4-byte patterns).
It also asserts, from the parsed central directories, that every selected
member is at least 200,000 compressed bytes. Genuine samples measure about 0%
on the lattice (at most 1 value in 105,840) and at least 105,039 distinct
patterns. The excluded 1542 mic-5 member measures 100% and 192.

The sample index (`index/<id>/samples.jsonl`) records for every sample its
numClosed, numComb, receiver, sweep, the 55-character panel state from
`combinations_setup.csv` (0 = reflective, 1 = absorptive), the source archive
and member, the member CRC-32, SHA-256, and min/max computed from the stored
float32 values.

## Acquisition without whole-archive downloads

The WAVs sit inside six DEFLATE ZIP archives of 4.3-9.7 GB (50.9 GB in
total). `IR_Arni_upload_numClosed_0-5.zip` has a classic end-of-central-
directory record. The other five need the ZIP64 EOCD locator/record and the
ZIP64 extended-information extra field (0x0001) for the 65,196 local-header
offsets above 4 GiB. `download.sh` uses curl byte ranges only:

1. Fetch the record JSON and check its identity, the `cc-by-4.0` license,
   and each file's size and MD5.
2. Fetch `combinations_setup.csv` (1.2 MB) and check its MD5 and SHA-256.
3. For each archive, fetch a 64 KiB tail, locate the central directory
   (classic or ZIP64), fetch it exactly, and check each 206 response's
   Content-Range against the pinned archive size.
4. Re-derive the selection from the six central directories. It must match
   the pinned `zip_archives.tsv` byte for byte (including the
   central-directory SHA-256) and the pinned `selection.tsv`.
5. For each of the 265 members, range-GET the local header plus compressed
   data (with 4 KiB of slack, because the local extra field differs from the
   central one: 0 vs 36/48 bytes), then:
   - inflate the raw DEFLATE stream and require the exact compressed
     boundary;
   - check the CRC-32 against the central directory;
   - check the WAV structure: fmt (3, 1, 44100, 176400, 4, 32), a `fact`
     length of 105,840, and that the `PEAK` chunk equals max |x| and its
     position;
   - reject NaN/Inf, all-zero or constant data, and int16-lattice or
     low-distinct (widened integer) data.
6. Run the receiver-distinctness check described above.

About 280 requests are throttled to roughly one per second. curl retries
408/429/5xx with backoff. Re-runs keep validated WAVs, re-fetch any that fail
their checks, and delete (and log) cached WAVs that are not in the pinned
selection, such as members of earlier selections. A fresh transfer is about
122 MB (member ranges 102.7 MB, central directories 17.6 MB, CSV 1.2 MB). The
downloads directory holds about 131.5 MB: the inflated WAVs plus the
directories.

`discover.sh` (not part of the acceptance path) regenerates both pinned tables
from the live record and fetches only metadata.

## Build and verify

```bash
bash staging/aalto_arni_room_impulse_response_f32/download.sh
bash staging/aalto_arni_room_impulse_response_f32/build.sh
bash staging/aalto_arni_room_impulse_response_f32/verify.sh
```

`build.sh` reads only local files. It re-checks each WAV's size and CRC-32,
validates the WAV structure, cross-checks numClosed against the number of
reflective panels in `combinations_setup.csv`, and writes the samples, the
index and `filtered/<id>/ingest_stats.json`.

`verify.sh` re-derives every sample independently:

- it walks the RIFF chunks with its own minimal parser, not the build's;
- it checks CRC-32 against the archive central directories rather than the
  pinned table;
- it requires byte equality between each sample and its WAV `data` chunk;
- it recomputes finiteness, non-zero/non-constant content, min/max and
  SHA-256 from the stored float32 bytes, and rejects duplicate samples;
- it checks the 53 × 5 scope (numClosed 0..55 except 11, 27, 35), that no
  numComb in 2..31 is selected, the 200,000-byte compressed-size floor,
  receiver distinctness, the float-lattice and distinct-pattern limits, the
  panel table, stray files, and the manifest sample count and total size.

## Notes

- The values are genuine floats, enforced by the float-lattice check above.
  Across the 265 selected WAVs, peak |x| ranges from 1.61e-3 to 2.38e-2
  (median 6.47e-3), and values span -2.23e-2..2.38e-2. The RMS of the
  2.0-2.4 s noise tail ranges from 2.63e-7 to 2.41e-6 (median 2.07e-6), with
  no outliers. `verify.sh` logs these figures. The decay reaches the measurement-noise floor after about
  0.5-0.8 s for numClosed below 30 and about 1.0-1.55 s for the most
  reflective levels, so much of each 2.4 s record is the low-level noise tail.
  This is real recorded material and no magnitude floor is applied.
- All 265 samples come from one room, one source, one measurement chain and
  one format. Only the panel configuration and the receiver position vary.
- Novelty: a new source of measured RIRs and the first 32-bit audio family.
  The RIR modality already exists at 16-bit (`openslr_rirs_noises_pcm16`).
