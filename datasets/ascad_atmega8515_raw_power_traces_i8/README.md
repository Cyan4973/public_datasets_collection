# ascad_atmega8515_raw_power_traces_i8

Raw int8 side-channel oscilloscope acquisitions from ANSSI's ASCAD v1 (fixed-key)
campaign. The device is an ATMega8515 running masked AES-128. Each sample is one
complete 100,000-point acquisition: row *i* of the HDF5 dataset `/traces`
(60,000 × 100,000, `H5T_STD_I8LE`) in `ATMega8515_raw_traces.h5`.

## Source and license

- Portal: data.gouv.fr dataset `ascad` (id `5aaa829dc751df2fbd43eacb`), published
  by ANSSI. The API record declares `"license": "fr-lo"` (Licence Ouverte / Open
  Licence, flagged OKD-compliant). `download.sh` checks the slug, title,
  organization, license, resource URL, filesize and sha1 on every run.
- Archive: `https://static.data.gouv.fr/resources/ascad/20180530-163000/ASCAD_data.zip`
  (4,435,199,469 B, sha1 `fb8c8a71…666a`).
- Code companion: github.com/ANSSI-FR/ASCAD (BSD). This is not relied on for the data license.
- Not used: the separate *variable-key* ASCAD dataset on data.gouv.fr, whose
  license is `notspecified`.

## Acquisition path (no full 4.4 GB download)

1. A 4 KB range GET of the zip tail (pinned sha256). It holds the zip64 EOCD and
   the central directory. They confirm that member
   `ASCAD_data/ASCAD_databases/ATMega8515_raw_traces.h5` uses method 8 (DEFLATE),
   crc32 `1cf4a0bf`, compressed size 2,966,104,128, uncompressed size
   6,003,842,144 and local header offset 72,006,934.
2. A range GET of archive bytes 72,006,934 .. +92,000,000. This covers the local
   header plus the head of the DEFLATE stream. The fetch resumes by appending
   sub-ranges, and a 200 full-archive response is refused via `--max-filesize`.
3. The DEFLATE prefix is inflated as a stream (`zlib.decompressobj(-15)`) into an
   exact prefix of the HDF5 file. A pure-stdlib parser reads:
   - superblock v0 (8-byte offsets, EOF address = 6,003,842,144 = member size)
   - the root group symbol table (B-tree, local heap, SNOD), whose links are
     `metadata` and `traces`
   - the `traces` v1 object header: dataspace dims, a signed little-endian 8-bit
     fixed-point datatype, no filter pipeline, and a v3 contiguous layout
   The parser asserts that the parsed values equal the expected values:
   dims 60000 × 100000, address 3,842,144 and size 6,000,000,000.
4. Rows 0..1499 are written verbatim as `trace_00000.bin` … `trace_01499.bin`
   (100,000 B each, int8) in acquisition order. Only complete traces are written.

At about 2.1:1 DEFLATE ratio in the trace region, 1,500 traces need about 74 MB of
compressed stream. The 92 MB range leaves about 20% margin.
`download.sh` fails if the prefix does not inflate past trace 1,499.

## Output

- 1 primary series `ascad_atmega8515_raw_trace_i8`: 1,500 samples × 100,000
  int8 values = 150,000,000 B.
- Index: `index/<id>/samples.jsonl`. Each row also records per-trace
  min/max/distinct/mean/std/order-0 entropy and the sha256.
- Stats: `filtered/<id>/ingest_stats.json`, which includes the inter-trace
  statistics below.
- Not emitted: the `/metadata` compound dataset (plaintext, key, masks).

## Near-duplicate concern: measured statistics

The traces are synchronized captures of the same AES execution, so traces look
alike at the same time index. The values below come from the full build: all
1,500 emitted traces, recorded in `ingest_stats.json`.

| statistic | value |
|---|---|
| distinct int8 values per trace | 115–122 (median 119) |
| value range (all traces) | −71 … 58 |
| order-0 entropy per trace | ≈ 6.4 bits |
| total variance (all values) | 693.5 LSB² |
| mean per-time-index inter-trace variance | 5.80 LSB² (0.84% of total) |
| adjacent-trace mean \|diff\| | 0.91 / 2.10 / 7.61 LSB (min / median / max) |
| identical adjacent traces | 0 (verify also rejects any exact duplicate) |

So within one trace, the waveform (the clock-driven EM signal, about 26 LSB std)
is the dominant structure. Across traces, the noise plus data-dependent leakage
term is small (about 2.4 LSB std per time index). A compressor that sees one
sample at a time gets a rich 100k-point waveform. A cross-sample model would find
the traces strongly mutually predictable. This is why the subset is bounded at
1,500 rather than all 60,000.

## Notes / caveats

- The 92,000,000-byte range sha256
  `256f0a930c6521befbc7ab72352c6d7e6d1535f140a09c5b0a85466caf65cc41` was pinned
  from the first driver download (2026-10-08). `download.sh` checks this hash in
  addition to the structural checks.
- Aggregate sha256 of the 1,500 emitted traces:
  `8de1a40097e501b2ddf9dd5b4173bfa189d7b6b61396d694c2963fd9be75a657`.
- `verify.sh` reuses the parser module, but it re-inflates and re-parses from the
  downloaded bytes, then byte-compares every sample and checks the index and
  aggregate hashes.
