# MetaClean Positive-Control Flow Cytometry UInt32

This recipe extracts native unsigned-32-bit event measurements from nine exact
FCS 3.1 positive-control files released with the MetaClean3.0 method under CC
BY 4.0.

Run:

```bash
bash datasets/zenodo_metaclean_fcs_u32/download.sh
bash datasets/zenodo_metaclean_fcs_u32/inspect.sh
bash datasets/zenodo_metaclean_fcs_u32/build.sh
bash datasets/zenodo_metaclean_fcs_u32/verify.sh
```

Each output sample is one complete event-by-channel matrix. The 64 retained
columns are the source scatter, fluorescence, pulse-height/area/width, and time
measurements. Three instrument bookkeeping fields (`TLSW`, `TMSW`, and
`Event Info`) are validated but excluded. Event order and native little-endian
uint32 words are preserved exactly.
