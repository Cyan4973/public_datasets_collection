# Egyptian fruit bat colony vocalization recordings (int16, 250 kHz)

This recipe collects 400 whole recordings from the Egyptian fruit bat
(*Rousettus aegyptiacus*) vocalization dataset of Prat, Taub, Pratt and
Yovel (Tel Aviv University; Scientific Data 2017; figshare collection
3666502 v2, CC0). The full dataset holds 293,238 triggered recordings made
around the clock in acoustically isolated colony and isolation chambers
between June 2012 and February 2014. Each recording is a 250 kHz, mono,
16-bit PCM WAV file of a second or two that contains bat vocalizations
(social calls, pup isolation calls, sometimes echolocation clicks) and the
surrounding background. Each selected recording becomes one sample: its
complete PCM data chunk, stored as raw little-endian int16.

The WAV files are stored as LZMA members (ZIP method 14) of 30 ZIP archives
totalling 97.8 GB. The recipe never downloads an archive whole. It
range-fetches the archive listings and then only the 400 members it keeps:
about 194 MB of downloads for about 368 MB of output.

## Material

- Quantity: sound pressure at one omnidirectional electret ultrasound
  microphone (Avisoft-Bioacoustics Knowles FG-O), digitized by an
  Avisoft-Bioacoustics UltraSoundGate 1216H at 250,000 samples/s, 16 bits.
  The values are the stored PCM codes. There is no gain, filtering,
  resampling, or trimming to the annotated voiced segments.
- Every selected file must declare fmt = (PCM 1, 1 channel, 250000 Hz,
  500000 B/s, block align 2, 16 bits); anything else is fatal. The RIFF
  layout seen so far is `fmt`, `data`, `TIME`, `bext`. The Avisoft `TIME`
  and `bext` metadata chunks are not emitted.
- Lengths in the pinned selection: 641,666 to 3,574,402 WAV bytes, median
  739,970. That is about 320k to 1.79M samples per recording, median about
  369k (about 1.5 s).
- Realized output (2026-10-06): 400 samples, 0 exclusions, 184,216,832
  values, 368,433,664 bytes, aggregate sha256 `410e512e…c284eb`. Every
  member has the RIFF layout `fmt,data,TIME,bext`. Per-recording peak
  |x| ranges from 1,069 to 32,767 (median 4,621), and distinct codes from
  509 to 18,410 (median 2,325). 78 full-scale codes occur, in 2
  recordings. The closest two selected recordings are 5,263 s apart.
- Not emitted: annotations, video, FileInfo voiced-segment positions. The
  treatment, channel, recording time and FileInfo FileID of each sample are
  written to the sample index as bookkeeping only.

### Homogeneity

All recordings come from one lab setup with the same microphone model, A/D
converter, sampling rate and bit depth, and the setup is described once in
the paper's Methods. Treatments (adult colonies, pup colonies,
mother-and-pup isolation) and channels are behavioural and placement
contexts, not acquisition changes. The recipe excludes the separately
curated "Example of ..." audio articles of the same collection.

### Selection

There is one sample per natural record, a whole WAV recording, taken evenly
across the whole collection:

1. Order all 293,238 members by archive (files101-106, then files201-224)
   and central-directory order. Within an archive this is file-name order,
   which is recording-time order, and the archives are chronological.
2. Place 400 targets at `t_k = floor((2k+1) * 293238 / 800)`.
3. For each target, take the first member at or after it (and before the
   next target) that meets all of these conditions:
   - it is a `^[0-9]{18}\.WAV$` method-14 member;
   - FileInfo.csv lists it with Treatment ID 1-20 (Treatment 0 has 102
     files and is not in the paper's treatment table);
   - its FileInfo recording time is more than 10 s from every member
     already taken.

The 10 s rule addresses a caveat in the paper: simultaneous files on
different channels of the same treatment can be two recordings of the same
call. In FileInfo, 38% of files have a partner on another channel within
2 s. With a stride of about 733 files, the rule removed no target from the
pinned selection.

Realized selection: all 30 archives; treatments 1, 2, 6, 8, 9, 10, 14, 16,
17, 18, 19 and 20 (roughly in proportion to their file counts, with the pup
colonies 16 and 17 and the adult colonies 9, 10 and 2 dominating); 12
recording channels; 2012-06-01 to 2014-02-18. `members.tsv` pins every
selected member's archive, name, central-directory index, offsets, span,
compressed and uncompressed sizes, CRC32, and FileInfo metadata.
`archives.tsv` pins every archive's figshare article id, file id, size,
md5, entry count, central-directory offset and size, and the sha256 of its
central directory. `discover.sh` documents how both tables were produced
and reproduces them from scratch.

## Novelty

This is a new source with new content in a known modality. PCM16 audio
already exists locally (ESC-50, LibriSpeech, NSynth, FSDD, OpenSLR RIRs,
CirCor phonocardiograms), but no recipe, registry row, ledger row or
downstream family covers animal bioacoustics or ultrasonic-band recording.
`novelty.py` finds only unrelated same-host figshare recipes (Fukuchi gait,
rMD17). At 250 kHz the band reaches about 125 kHz: the material holds
frequency-modulated social calls and clicks well above the audible band,
with the chamber background between them. This is a different signal
regime from the 4-44.1 kHz speech, music, environmental and heart-sound
audio already in the corpus.
Within this collection effort, the only accepted 16-bit audio family so far
is CirCor.

## Source and rights

- Data: figshare collection https://doi.org/10.6084/m9.figshare.c.3666502.v2
  (Springer Nature figshare). Files are served by `ndownloader.figshare.com`,
  which redirects to a presigned S3 URL valid for 10 seconds. Every request
  therefore goes through ndownloader again with `curl -L`.
- License: CC0 1.0. The figshare API reports
  `"license": {"value": 2, "name": "CC0", "url": "https://creativecommons.org/publicdomain/zero/1.0/"}`
  for all 30 archive articles and for FileInfo.csv. `download.sh` re-fetches
  the article JSON and fails if the license, file id, name, size or md5
  differ. The Scientific Data article (CC BY 4.0) states that the CC0 waiver
  applies to its data.
- Citation: Prat, Y., Taub, M., Pratt, E. & Yovel, Y. (2017). An annotated
  dataset of Egyptian fruit bat vocalizations across varying contexts and
  during vocal ontogeny. *Scientific Data* 4, 170143,
  doi:10.1038/sdata.2017.143.
- Safety: animal recordings from a laboratory colony. There are no human
  subjects and no personal data.

## Running

Run from the repository root:

```bash
bash staging/figshare_rousettus_vocalizations_i16/download.sh   # ~194 MB, ~490 small GETs
bash staging/figshare_rousettus_vocalizations_i16/build.sh
bash staging/figshare_rousettus_vocalizations_i16/verify.sh
```

`ROUSETTUS_PARALLEL` (default 4) and `ROUSETTUS_MAX_PASSES` (default 8)
tune the member fetch.

### `download.sh`

1. Fetches the figshare API JSON for the 30 archive articles and the
   FileInfo.csv article.
2. Range-fetches the last 1,024 bytes of each archive and parses its EOCD.
   files201 and files202 exceed 4 GiB and carry ZIP64 EOCD records, which
   are parsed rather than skipped.
3. Range-fetches each central directory: 30,505,800 bytes, 293,238 entries,
   each directory sha256-pinned.
4. Fetches FileInfo.csv (31,574,701 B, md5 and sha256 pinned). This step is
   resumable.
5. Runs `rousettus.py check-metadata`:
   - license and identity from the API JSON;
   - EOCD fields against `archives.tsv`;
   - central-directory sha256;
   - FileInfo checksums;
   - a re-derivation of the selection, which must equal `members.tsv`
     byte for byte.
6. Fetches the 400 member spans with `xargs -P 4` and `scripts/fetch_span.sh`
   (131,291,409 B). Each request asks for exactly
   `[local header offset, next member offset)` and keeps the response
   headers. `check-members` then checks each span:
   - the `Content-Range` must name the requested span and the pinned
     archive size;
   - the span must decode fully (raw LZMA1), with CRC32 equal to the
     central directory's;
   - the WAV fmt must be exactly as above.

   Invalid spans are deleted and refetched, up to 8 passes. `--max-filesize`
   stops curl if a server ignores the range.

### `build.sh`

The build runs the synthetic self-test and re-derives the selection. Then,
for each member, it:

1. validates the local header against the central directory;
2. decodes method 14: a 2-byte LZMA SDK version, a 2-byte properties size
   (5), then the properties byte (lc/lp/pb) and a u32 dictionary size, fed
   to `lzma.LZMADecompressor(FORMAT_RAW, FILTER_LZMA1)` up to exactly the
   uncompressed size. The archives' streams have no end marker (flag bit 1
   clear); a set bit 1 would require one. Without an end marker the raw
   decoder cannot tell where the stream stops, so the range coder's final
   flush bytes can decode into a few spurious bytes past the declared size.
   In the pinned selection this happens once: one `0x00` byte in
   `files205_121110190908022381`. As in 7-Zip and Python's `zipfile`, the
   declared size bounds the output. The tail is tolerated only if it is at
   most 1,024 bytes and consumes all remaining input; it is reported in
   `ingest_stats.json` as `lzma_flush_overrun_bytes`, and the CRC32 of the
   declared-size prefix must still match;
3. checks the CRC32;
4. walks the RIFF chunks and writes the data chunk unchanged to
   `samples/figshare_rousettus_vocalizations_i16/rousettus_vocalization_pcm_i16/<archive>_<member>.bin`.

Recordings with fewer than 64 distinct codes, or with PCM identical to an
earlier selected recording, are excluded and listed. More than 1%
exclusions is fatal. The build writes `index/.../samples.jsonl` and
`filtered/.../ingest_stats.json` (totals, treatment counts, RIFF layouts,
full-scale count, aggregate sha256).

### `verify.sh`

1. Re-derives the selection from the local central directories and
   FileInfo.csv, checks the members' FileInfo metadata, and checks the 10 s
   separation.
2. Re-decodes every member independently of the build decoder: it wraps the
   fetched local entry in a one-entry ZIP carrying the real central-directory
   CRC and sizes, extracts it with the stdlib `zipfile` module (its own
   method-14 handling and CRC check), and reads the frames with `wave`.
3. Compares the sample bytes and every index field, re-applies the exclusion
   rule, and checks for constant samples.
4. Checks the aggregate sha256, the floors, the 1 GB cap and the manifest
   totals.

## Self-tests

Both build and verify first run `rousettus.py selftest`, which covers:

- synthetic WAVs with Avisoft-like trailer chunks, written by `zipfile`
  with `ZIP_LZMA` (end-marker variant, including a forced-ZIP64 local
  header) and decoded by both paths;
- a hand-built method-14 header, including the overrun bounds: a 1-byte
  tail past the declared size is accepted when no end marker is declared;
  a tail of more than 1,024 bytes, or any tail when an end marker is
  declared, is rejected;
- a ZIP64 central-directory extra field (offset above 4 GiB) and a ZIP64
  EOCD;
- rejection of corrupted LZMA data, a wrong CRC, an inconsistent EOCD, and
  a stereo WAV.

The no-end-marker LZMA variant cannot be produced with the standard
library, so the real members exercise it. Two real members, one above the
4 GiB offset in files201, were range-fetched and decoded with both paths
during authoring, and a 3-member end-to-end run of
download/build/verify passed in a scratch directory. The first full
download rejected the files205 member above, because the original check
treated the 1-byte flush tail as an error. Its first 674,434 decoded bytes
match the central-directory CRC32, and `zipfile` extracts the same WAV. All
400 pinned members now decode identically through both paths.
