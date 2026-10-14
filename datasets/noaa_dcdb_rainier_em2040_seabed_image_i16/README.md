# noaa_dcdb_rainier_em2040_seabed_image_i16

Native signed-int16 Kongsberg EM2040 **seabed-image (beam snippet) backscatter**
samples (0.1 dB steps) from raw `.all` files of NOAA Ship Rainier survey
project RICHARD2023L4. The files were logged on 2023-04-30 by survey launch 2802
(EM2040 system serial 40129) in the central Pacific, about 2.8 S 171.7 W.

## Source

- Bucket: `s3://noaa-dcdb-bathymetry-pds` (NOAA NODD on AWS, anonymous HTTPS).
- Folder: `mb/ships/rainier/RICHARD2023L4/multibeam/data/version1/MB/em2040/`.
  It holds 36 raw `*_2802.all.mb58` files (8.17 GB). The `.mb58` suffix is
  MB-System's format id 58 (MBF_EM710RAW): the bytes are the unmodified
  Kongsberg `.all` datagram stream. The folder also holds 10 S221 `.kmall`
  files (another system and format) and MB-System derivatives under
  `generated/`. Both are excluded.
- Collected: the **20 smallest** raw files (2,442,068,200 bytes), each pinned by
  size and S3 ETag (5 MiB multipart MD5, recomputed locally). The 16 larger
  files (252–830 MB) are left out to keep the download near 2.4 GB and the
  primary output under 1 GB.
- License: the AWS Open Data registry entry for the bucket says "NOAA data
  disseminated through NODD are open to the public and can be used as
  desired ... NOAA requests attribution for the use or dissemination of
  unaltered NOAA data", and forbids implying endorsement. The data come from a
  U.S. Government (NOAA) survey.

## Output

| series | role | kind | one sample = |
|---|---|---|---|
| `em2040_seabed_image_backscatter_i16` | primary | int16 LE | all Y-datagram samples of one `.all` file, ping order |
| `em2040_beam_sample_count_u16` | auxiliary | uint16 LE | per-beam Ns (400 per ping) of the same file |

Each Y datagram (one ping) has 400 beams. Each beam carries Ns int16 samples
around the bottom detection (the "snippet"), in 0.1 dB with the sonar's
real-time TVG and BSN/BSO normalisation applied. The samples are copied
unchanged. Headers, beam entries, the pad byte, ETX and checksum are removed.
The auxiliary Ns series reshapes a primary sample into ping × beam snippets.

## Decoding and checks

`scripts/em2040_all.py` walks the whole datagram stream: u32 length, STX
0x02, type, model, ETX 0x03 and the 16-bit byte-sum checksum. Framing errors
are resynchronised to the next valid datagram. A file may lose at most 16
spans and max(0.1 %, 64 KiB) of its bytes, and each span is logged in
`filtered/<id>/ingest_stats.json`. The script asserts model 2040 on every
datagram, plus serial 40129 and 400 beams on every Y datagram. Each Y
datagram's length must match header + 6·Nbeams + 2·ΣNs + optional zero pad
+ 3. Timestamps must not decrease and there must be no duplicate pings.
`scripts/verify_em2040.py` is a separate reader: it re-derives each payload
and compares it byte for byte. It also recomputes the stored min/max, distinct
values and zero/-32768 counts, and checks the manifest totals and
degeneracy.

## Probe facts (2026-10-14)

- Serial in Y headers is 40129. "2802" in the file names is the launch
  number, not the sonar serial.
- The sampling frequency varies with depth mode, even within one file:
  9077.7, 20424.8 and 30637.3 Hz were seen. The unit, scale and lattice
  (0.1 dB int16) stay the same. Per-file mode mixes are recorded in the index.
- The trailing pad byte is always present and always zero.

## Realized build (2026-10-14)

- 20 files, 173,387,341 int16 values, 346,774,682 primary bytes; auxiliary
  Ns series 87,736,800 bytes. Zero unframed spans in any file.
- The Y fraction is lower than the prefix probes suggested: about 13–14 % of
  file bytes in the 13 large files logged entirely in the 30.6 kHz mode
  (about 3.8 samples per beam), and 20–35 % in the short mixed-mode files
  0030–0036.
- No -32768 or other fill codes. Zeros are rare (175–5,766 per file).
  927–1,797 distinct values per file; global range -1235..+1066.
- File 0035 is the only file logged entirely in the 9.08 kHz mode. Its level
  is clearly higher (median -7.9 dB vs about -19.7 dB in 0004; 99th
  percentile +52 dB; 3.8 % of values above +20 dB; max +106.6 dB). The
  values are kept as logged (same field, unit and lattice), but this file is
  a distinct acquisition regime within the series.

## Run

```bash
bash staging/noaa_dcdb_rainier_em2040_seabed_image_i16/download.sh
bash staging/noaa_dcdb_rainier_em2040_seabed_image_i16/build.sh
bash staging/noaa_dcdb_rainier_em2040_seabed_image_i16/verify.sh
```
