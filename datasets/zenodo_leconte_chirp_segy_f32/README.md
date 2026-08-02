# LeConte Bay CHIRP SEG-Y Float32

This candidate collects five bounded files from the CC BY 4.0 LeConte Bay
CHIRP subsurface survey on Zenodo. The files use SEG-Y sample format code `5`,
native IEEE float32.

Each SEG-Y trace becomes one natural sample. Trace order and every IEEE value
bit pattern are preserved; only the required big-endian-to-little-endian byte
order conversion is applied. The selected files total 127,053,172 source
bytes and expose several trace lengths.

Run:

```bash
bash datasets/zenodo_leconte_chirp_segy_f32/download.sh
bash datasets/zenodo_leconte_chirp_segy_f32/build.sh
bash datasets/zenodo_leconte_chirp_segy_f32/verify.sh
```

The downloader pins every URL, size, and MD5. Build and verification are local
after acquisition.

Validated output: 6,895 natural traces, 31,345,093 float32 values, and
125,380,372 bytes across nine observed trace lengths.
