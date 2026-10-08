# MIMII industrial solenoid valve sounds, 8-channel microphone array (int16, 16 kHz, 6 dB SNR)

This recipe collects 160 whole 10-second clips from the valve recordings of
the MIMII dataset ("Sound Dataset for Malfunctioning Industrial Machine
Investigation and Inspection", Hitachi, Ltd.; DCASE 2019 workshop; Zenodo
record 3384388, version "public 1.0", CC BY-SA 4.0). Each clip is an
8-channel WAV recorded with a circular microphone array next to an industrial
solenoid valve, in normal operation or with a contamination fault. The
publisher mixed real factory background noise into each clip at a fixed
signal-to-noise ratio. Each selected clip becomes one sample: its complete
PCM data chunk, 160,000 interleaved frames x 8 channels, stored as raw
little-endian int16.

Only the **6 dB SNR valve product** (`6_dB_valve.zip`) is used. The -6 dB and
0 dB products, and the fan, pump and slider machine types, are separate
regimes and are not mixed in.

The clips are deflate members of one 6,915,951,837-byte ZIP64 archive. The
recipe never downloads the archive whole. It range-fetches the archive's
central directory and then only the 160 members it keeps: about 265.5 MB of
downloads for 409.6 MB of output.

## Material

- Quantity: sound pressure at the eight microphones of a TAMAGO-03 circular
  microphone array (System In Frontier Inc.), placed 10 cm from the valve,
  recorded "as 16-bit audio signals sampled at 16 kHz in a reverberant
  environment" (MIMII paper, section 2). The valves "are solenoid valves
  that are repeatedly opened and closed"; the paper lists the valve
  anomalies as "more than two kinds of contamination".
- **Publisher-mixed noise.** The clean machine recordings are not published.
  Background noise was recorded continuously in several real factories with
  the same array and mixed into each machine clip channel by channel. For
  each product model the publisher computed `a`, the mean power over all of
  that model's clips. For each clip it picked a random noise segment `j`,
  with power `b_j`, and scaled the noise so that `10 log10(a / b_j)` equals
  the target SNR (here 6 dB) before adding it. The material is therefore
  machine sound plus real factory noise at a fixed per-model ratio. This
  mixed product is the published material; the recipe does not alter it.
- Values: the stored PCM codes, unchanged and in the stored interleaved order
  (frame-major, channel fastest; shape `[160000, 8]`). There is no gain,
  filtering, resampling, channel selection, de-interleaving or mixing.
- Every selected file must declare exactly this fmt: WAVE_FORMAT_EXTENSIBLE
  (`0xFFFE`), 8 channels, 16000 Hz, 256000 B/s, block align 16, 16 bits,
  cbSize 22, 16 valid bits, subformat GUID `KSDATAFORMAT_SUBTYPE_PCM`
  (`00000001-0000-0010-8000-00aa00389b71`). It must also have a `fact`
  chunk of 160,000 frames and a data chunk of exactly 2,560,000 bytes;
  anything else is fatal. The RIFF layout seen in the authoring probes is
  `fmt ` (40 B), `fact`, `data`. The fmt channel mask `0x0000063F` is a
  nominal surround mask written by the recording tool, not a speaker
  layout.
- Realized output (2026-10-06): 160 samples (40 per model, 10 abnormal and
  30 normal each), 0 exclusions, 204,800,000 values, 409,600,000 bytes.
  The aggregate sha256 is
  `efd9215c50362b3918751d831e14d88742c19e4789717123d089193dd22ac754`.
  - Every member has the RIFF layout `fmt ,fact,data` and channel mask
    `0x0000063F`.
  - Per-clip peak |x| ranges from 2,578 to 16,675 (median 8,122), and
    distinct codes from 1,921 to 6,375 (median 4,028). There are no
    full-scale codes.
  - Levels differ by model and condition because the SNR scaling is per
    model. For example, id_00 abnormal clips are quiet (median peak 2,756,
    against 8,658 for id_00 normal), and their channels are strongly
    correlated (about 0.97 between neighbours). id_02 abnormal clips are
    the loudest (median peak 13,319).
  - No two channels of a clip are identical. Spot-checked neighbour-channel
    correlations range from 0.39 to 0.98.
- Download: 265,549,260 bytes (one pass, no rejected or refetched spans,
  about 3.5 minutes).

### Homogeneity

The family is one machine type (solenoid valves), one SNR product (6 dB),
one microphone array at one distance, and one format (8 ch / 16 kHz /
PCM16), with fixed 10 s clips. All of it comes from one recording campaign,
described once in the paper. The four product models and the
normal/abnormal conditions are operating states and units of the same
machine type, not acquisition changes. Model id and condition go to the
sample index as bookkeeping only.

### Selection

There is one sample per natural record: a whole 10-second WAV clip.

1. Group the 4,170 WAV members by (product model, condition). The group
   sizes must equal the pinned values, which also match Table 1 of the
   paper:

   | model | normal | abnormal |
   |---|---|---|
   | id_00 | 991 | 119 |
   | id_02 | 708 | 120 |
   | id_04 | 1000 | 120 |
   | id_06 | 992 | 120 |

2. Within each group, ordered by member name, take K evenly spaced members
   at ranks `floor((2k+1) * N / (2K))`, with K = 30 for normal and K = 10
   for abnormal.
3. That gives 40 clips per model: 120 normal and 40 abnormal in total.
   Abnormal clips are over-represented relative to their share of the
   source (about 11%) so that the fault regime is not a sliver of the
   family.

`members.tsv` pins every selected member's sample id, model, condition,
name, central-directory index, group size and rank, local-header offset,
span, compressed and uncompressed sizes, and CRC32. The archive size, md5,
entry count, central-directory offset and size, and the sha256 of the
fetched tail are pinned in `scripts/mimii.py`. `discover.sh` reproduces
`members.tsv` from scratch; it was run on 2026-10-06 and matched.

Why 160 clips: the source holds 4,170 clips (10.7 GB of PCM). The
criteria's downstream sub-sampling is roughly 100 MB per family, and the
screener suggested 100-200 clips. 40 clips per model covers all four
published models and both conditions at about 410 MB, well under the 1 GB
cap.

## Novelty

This is a **new source** with new content in a known modality.

- PCM16 audio already exists locally: ESC-50, LibriSpeech, NSynth, OpenSLR
  RIRs, CirCor phonocardiograms, and the Rousettus bat vocalizations.
- `novelty.py --url https://zenodo.org/records/3384388 --terms MIMII ToyADMOS DCASE "machine sound" "microphone array"`
  finds only unrelated same-host Zenodo recipes. No recipe, registry row,
  or downstream family covers industrial machine-condition acoustics or
  multichannel microphone-array audio.
- What is different here: an 8-microphone array (strongly inter-channel
  correlated, interleaved frames) recording periodic mechanical transients
  (valve open/close clicks) over stationary factory noise.

**Breadth caveat.** Within this collection effort, this would be the third
16-bit audio family, after `physionet_circor_pcg_i16` and
`figshare_rousettus_vocalizations_i16`. The breadth guideline in
`tools/autocollect/criteria.md` makes it lower value even though the source
is new.

## Source and rights

- Data: Zenodo record https://zenodo.org/records/3384388
  (doi:10.5281/zenodo.3384388), version "public 1.0", the latest version of
  concept record 3384387. Files are served directly by zenodo.org
  (`/api/records/3384388/files/6_dB_valve.zip/content`) with HTTP range
  support; there is no redirect.
- License: **CC BY-SA 4.0.** The record description states: "This dataset is
  made available by Hitachi, Ltd. under a Creative Commons
  Attribution-ShareAlike 4.0 International (CC BY-SA 4.0) license." The
  record metadata license id is `cc-by-sa-4.0` and access_right is `open`.
  `download.sh` re-fetches the record JSON and fails if the license id, that
  sentence, access_right, the version, or the pinned file key, size or md5
  change.
- **Attribution** (required): credit Hitachi, Ltd. and the authors, link the
  record and the license, and indicate changes. The changes here: members
  extracted from the ZIP, RIFF headers stripped, PCM data chunk kept byte
  for byte.
- **ShareAlike** (required): adapted material that is shared must be offered
  under CC BY-SA 4.0 or a compatible license, and redistributed samples must
  keep this attribution and license.
- Citation: Harsh Purohit, Ryo Tanabe, Kenji Ichige, Takashi Endo, Yuki
  Nikaido, Kaori Suefusa, and Yohei Kawaguchi, "MIMII Dataset: Sound Dataset
  for Malfunctioning Industrial Machine Investigation and Inspection," in
  Proc. 4th Workshop on Detection and Classification of Acoustic Scenes and
  Events (DCASE), 2019; arXiv:1909.09347.
- Safety: recordings of industrial machines with factory background noise.
  The dataset targets no speech content, involves no human subjects, and
  contains no personal data.

## Running

Run from the repository root:

```bash
bash staging/zenodo_mimii_valve_mic_array_i16/download.sh   # ~265.5 MB, ~163 range GETs
bash staging/zenodo_mimii_valve_mic_array_i16/build.sh
bash staging/zenodo_mimii_valve_mic_array_i16/verify.sh     # Python 3.12+
```

`MIMII_PARALLEL` (default 2), `MIMII_REQUEST_DELAY` (seconds after each
member request, default 1.2) and `MIMII_MAX_PASSES` (default 8) tune the
member fetch.

### `download.sh`

1. Sends a one-byte range GET (`-L`). The `Content-Range` total must equal
   6,915,951,837 and the first byte must be `P`.
2. Fetches the record JSON (about 10 KB) and checks the license and the
   file identity as above.
3. Range-fetches bytes 6,915,459,463 to the end of the archive (492,374
   bytes): the central directory, ZIP64 EOCD record, ZIP64 locator and EOCD.
   The sha256 must be
   `209786dc47b446d51160124a79a9e23a8600142e93fb79512ab08730cb9cd0ae`.
4. Runs `mimii.py check-metadata`:
   - parses the EOCD (32-bit cd offset is the `0xFFFFFFFF` sentinel), the
     ZIP64 locator and the ZIP64 EOCD record (4,183 entries);
   - parses every central-directory entry, widening ZIP64 offsets above
     4 GiB from the `0x0001` extra;
   - checks the group sizes;
   - re-derives the selection, which must equal `members.tsv`.
5. Fetches the 160 member spans (265,037,035 B) with `xargs -P 2` and
   `scripts/fetch_span.sh`. Each request asks for exactly
   `[local header offset, next central-directory entry offset)`, keeps the
   response headers, and is followed by a 1.2 s pause. Zenodo reported
   `X-RateLimit-Limit: 133` per minute; curl retries 429 and 5xx with
   `--retry-all-errors` and honours `Retry-After`. `check-members` then
   checks each span:
   - the `Content-Range` must name the requested span and the archive
     size;
   - the local header must agree with the central directory, read with
     its own name and extra lengths (the local extras were 0 bytes in
     every probed member, while the central-directory extras are 36 or 48
     bytes, so the latter are never reused). 54 of the 160 members start
     above the 4 GiB offset;
   - the span must inflate fully to 2,560,080 bytes with the central
     directory's CRC32;
   - the WAV must have exactly the fmt, fact and data described above.

   Invalid spans are deleted and refetched, up to 8 passes, with a 60 s
   pause between passes. `--max-filesize` stops curl if a server ignores
   the range.

### `build.sh`

The build runs the synthetic self-test and re-derives the selection. Then,
for each member, it:

1. validates the local header against the central directory;
2. inflates with `zlib.decompressobj(-15)`; the stream must end exactly at
   the span end, produce exactly the declared size, and match the CRC32;
3. walks the RIFF chunks and checks the fmt, GUID, fact and data size;
4. writes the data chunk unchanged to
   `samples/zenodo_mimii_valve_mic_array_i16/mimii_valve_6db_array_pcm_i16/<model>_<condition>_<number>.bin`.

Clips with fewer than 64 distinct codes, a constant microphone channel, or
PCM identical to an earlier selected clip are excluded and listed. More
than 1% exclusions is fatal. The build writes `index/.../samples.jsonl`,
which per sample holds the shape, layout, rate, model, condition, member,
CRC32, sha256, min/max, per-channel min/max, distinct codes and full-scale
count. It also writes `filtered/.../ingest_stats.json`, with totals,
per-group counts, RIFF layouts, channel masks, peak and distinct-code
ranges, and the aggregate sha256.

### `verify.sh`

1. Re-derives the selection from the local archive tail and checks 30
   normal and 10 abnormal clips per model.
2. Re-decodes every member independently of the build decoder: it wraps the
   fetched local entry in a one-entry ZIP carrying the real
   central-directory CRC and sizes, extracts it with the stdlib `zipfile`
   module (its own inflate and CRC check), and reads the frames with the
   stdlib `wave` module. `wave` handles WAVE_FORMAT_EXTENSIBLE from Python
   3.12, so verify requires 3.12+.
3. Compares the sample bytes and every index field, re-applies the exclusion
   rule, and rejects constant samples.
4. Checks the aggregate sha256, the floors, the 1 GB cap and the manifest
   totals.

## Self-tests and authoring probes

Both build and verify first run `mimii.py selftest`, which covers:

- synthetic 8-channel WAVE_FORMAT_EXTENSIBLE clips (fmt 40 B, fact, an
  odd-sized padded LIST chunk, data), written by `zipfile` with
  `ZIP_DEFLATED`. One member forces a ZIP64 local extra that the central
  directory lacks, so the decoder must use the local header's own lengths.
  Both decoders must reproduce the PCM;
- a hand-built ZIP64 tail like the real one: EOCD with the `0xFFFFFFFF`
  offset sentinel, ZIP64 locator and record, and a central-directory entry
  with an NTFS extra plus a ZIP64 extra carrying only an offset above
  4 GiB;
- rejection of corrupted deflate data, a wrong CRC, a truncated span, a
  wrong name, a non-PCM subformat GUID, a 7-channel clip, a short data
  chunk and a plain-PCM format tag. It also checks that a constant
  channel is excluded and that the selection ranks are right.

During authoring (2026-10-06):

- A 600 KB tail read confirmed the ZIP64 layout and all pins.
- Four members were range-fetched and decoded: `id_00/abnormal/00000000`,
  `id_04/normal/00000546` (above the 4 GiB offset), and the two selected
  members above. The selected two went through `fetch_span.sh` and
  `check-members` into a scratch data root.
- A reduced build and verify (2 samples) passed there, and verify caught a
  single flipped byte in a sample.
- `discover.sh` reproduced `members.tsv` byte for byte.
