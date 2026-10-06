# Egyptian fruit bat vocalization PCM16 development

## Outcome

Accepted `figshare_rousettus_vocalizations_i16`: 400 whole triggered
ultrasonic-band recordings from the Prat, Taub, Pratt and Yovel (2017)
Egyptian fruit bat (*Rousettus aegyptiacus*) vocalization dataset. Each
recording is emitted as one native little-endian int16 PCM sample at 250 kHz,
mono.

This is the first animal bioacoustic family and the first ultrasonic family
in the local corpus. PCM16 audio already exists locally (ESC-50, LibriSpeech,
NSynth, FSDD, OpenSLR RIRs, CirCor phonocardiograms, accelerometer PCM16), but
all of it is sampled at 44.1 kHz or below. This material is sampled at 250 kHz
and holds frequency-modulated social calls over a broadband noise floor that
extends to 125 kHz. It is the second accepted 16-bit audio family in this
collection effort, after `physionet_circor_pcg_i16`. Further 16-bit audio
families are therefore lower value.

## Source and rights

- Source: figshare collection 3666502 v2,
  https://doi.org/10.6084/m9.figshare.c.3666502.v2 (published 2017-09-29).
  The collection holds 30 ZIP archives (files101–106, files201–224; 97.8 GB;
  293,238 LZMA WAV members) and FileInfo.csv (31,574,701 B, md5
  `b27252490ac5618bd55a9038110809d5`, sha256
  `753529d166f8cbb6f900fa54d3d5122d1e47bae5d6be59669e37f33e4cc1ed34`).
- License: CC0 1.0. The figshare API reports
  `{"value": 2, "name": "CC0", "url": "https://creativecommons.org/publicdomain/zero/1.0/"}`
  for every archive article and for the FileInfo.csv article. `download.sh`
  re-checks the license, file id, name, size and md5 of all 31 articles.
- Citation: Prat, Y., Taub, M., Pratt, E. & Yovel, Y. (2017), *Scientific
  Data* 4, 170143, doi:10.1038/sdata.2017.143.
- Safety: laboratory bat colony recordings. There are no human subjects, and
  the WAV `bext` chunk is empty.

## Shape and conversion

- Natural record: one triggered WAV recording, kept whole and not trimmed to
  the annotated voiced segments.
- Selection: 400 targets at `floor((2k+1)·293238/800)` over all members in
  archive order, then central-directory order (chronological). Each target
  takes the first member listed in FileInfo under Treatment 1–20 that is more
  than 10 s from every earlier pick. The 10 s rule guards against cross-channel
  duplicates of the same call. Neither rule skipped any target.
- Access: the recipe range-fetches each archive's tail (EOCD/ZIP64) and its
  central directory (30,505,800 B in total, each sha256-pinned), then fetches
  the 400 member spans (131,291,409 B). It never fetches a whole archive.
- Decode:
  1. Validate the ZIP local header against the central directory.
  2. Decode method-14 LZMA1 with stdlib `lzma` (FORMAT_RAW, per-member props:
     lc3/lp0/pb2, 128 MiB dictionary), truncating at the declared size.
  3. Check the CRC32 against the central directory.
  4. Walk the RIFF chunks (`fmt,data,TIME,bext` for all 400) and require fmt
     = (1, 1, 250000, 500000, 2, 16).
  5. Write the data chunk unchanged.
- LZMA overrun: one member, `files205_121110190908022381`, decodes one extra
  0x00 byte past the declared size. The stream has no end marker, and the
  extra byte comes from the range coder's final flush. It lies after the
  `bext` chunk, outside the PCM, and the CRC32 of the declared-size prefix
  matches.
- Verification path: `verify.sh` re-decodes every member with stdlib `zipfile`
  plus `wave` and compares the bytes and every index field.
- Effective resolution: every stored value is odd. The LSB is constantly 1, a
  15-bit mid-riser code in the int16 WAV word, with values spanning
  -32767..32767. This is native source coding, kept unchanged.

## Accepted output

- Universe: 293,238 recordings in 30 archives
- Primary samples: 400 (0 excluded)
- Primary values: 184,216,832
- Primary bytes: 368,433,664
- Sample length: minimum 320,336, median 369,488, maximum 1,786,704 values
  (1.28 s / 1.48 s / 7.15 s)
- Coverage:
  - all 30 archives (13–14 each; 5 from the smaller files106)
  - treatment counts: 1:25, 2:44, 6:1, 8:3, 9:70, 10:56, 14:1, 16:87, 17:66,
    18:13, 19:26, 20:8
  - 12 recording channels
  - 2012-06-01 to 2014-02-18
- Per-recording peak |x|: 1,069 to 32,767 (median 4,621). There are 78
  full-scale codes, in 2 recordings.
- Distinct codes per recording: 509 to 18,410 (median 2,325)
- Download: about 193.5 MB in total, all byte-range requests
- Aggregate decoded SHA-256:
  `410e512ee306b4698f0532d4963d50da51d04ec2e24a97e0662791ce07c284eb`

## Judge checks

- **Gate:** `gate.py` passed with no warnings.
- **Verify:** `verify.sh` passed on the judge's own run (exit 0, 26 s). It
  reproduced the aggregate sha256, the totals and 0 exclusions.
- **Local-only build:** `build.sh` and `verify.sh` use only local files. There
  is no curl in either script and no network module in `rousettus.py`. No
  script contains credentials.
- **Rights:** the judge read all 31 local article JSONs, all CC0, and
  re-fetched article 4556110 and collection 3666502 v2 to confirm the CC0
  record and the v2 DOI.
- **Bytes, all 400 samples:**
  - 0 even values out of 184,216,832, so the odd-code lattice holds
    throughout;
  - values range from -32767 to 32767;
  - sample sha256 values are all distinct.
- **Bytes, 12 samples:**
  - mean is about 0–2 codes;
  - lag-1 autocorrelation is 0.86–0.96;
  - the median |x| is 5–17 codes, so most of each file is a quiet background
    around louder calls.
- **Spectra:** a Hann-windowed 4096-point FFT on 9 samples gave consistent
  results.
  - Loud windows peak at 7–14 kHz, with 80–98% of their energy in 5–15 kHz
    (social calls).
  - Quiet windows are a flat noise floor of about 8–12 codes rms, with 55–65%
    of their energy above 60 kHz. The 250 kHz sampling is therefore genuine,
    not upsampled.
  - The noise floor is consistent across channels and treatments, which
    supports a single acquisition regime.
- **LZMA overrun:** the judge independently decoded the files205 member and
  confirmed the single 0x00 overrun byte past the trailing `bext` chunk.
- **Novelty:** `novelty.py` on the ndownloader URL and the collection DOI
  found only same-host figshare recipes and substring 'bat' hits (battery,
  bathymetry, BATSE). No bioacoustic or ultrasonic family exists in the
  recipes, the registry, the ledger or the downstream corpus.
- **Documentation gap:** the manifest does not mention the constant-LSB odd
  coding. This report records it. A future manifest touch should add it to
  `representation_notes`.
