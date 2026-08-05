# MetaClean flow-cytometry uint32 development — 2026-08-05

## Outcome

Accepted `zenodo_metaclean_fcs_u32`, nine native-uint32 flow-cytometry
positive-control event matrices from Zenodo record `10639508`, *MetaClean3.0:
Robust and accurate removal of low-quality event measurements in cytometry*,
DOI `10.5281/zenodo.10639508`, released under CC BY 4.0.

This is the width-correct successor lead discovered during the blocked
`zenodo_flow_cytometry_fcs_u16` search. A bounded scan of 499 conclusively
classified FCS files found no 16-bit payloads; these nine MetaClean files were
the only integer examples and uniformly declare 32 stored bits.

## Domain and shape distinction

This is the corpus's first accepted flow-cytometry family. Each FCS file is a
two-dimensional event-by-measurement matrix rather than an image, waveform, or
catalogue column. Keeping event-major order preserves correlations among pulse
height, area, and width and among scatter and fluorescence detector channels.

## Source and decoding

The exact nine-file FCS inventory totals 55,520,786 source bytes and is pinned
by individual size and MD5. Every source declares:

- FCS 3.1 list mode;
- integer data (`$DATATYPE=I`);
- 206,828 events in aggregate;
- one shared 67-parameter schema;
- 32 stored bits and a declared range of 2,147,483,647 for every parameter;
- little-endian byte order; and
- a producer-specific exclusive `$ENDDATA` boundary whose geometry exactly
  equals `$TOT × $PAR × 4` and ends at source EOF.

The first three parameters (`TLSW`, `TMSW`, and `Event Info`) are instrument
bookkeeping fields and are excluded. The remaining 64 source-contiguous words
per event comprise scatter, fluorescence, pulse height/area/width, and time
measurements and are copied byte-for-byte in source event order.

## Accepted material

- 9 complete event-by-64-channel matrices
- 206,828 total events
- 13,236,992 uint32 values
- 52,947,968 numeric bytes
- 9 unique sample payloads
- no duplicate event rows within or across files
- global selected-value range 225 through 2,147,483,392
- at least 1,006 distinct values and 10,381 transitions in every selected
  channel/file combination
- zlib-9 ratios approximately 0.759 through 0.761, median about 0.761

Independent verification reparses every source and byte-compares each emitted
matrix against the selected native FCS words.

## License and safety

The exact Zenodo record declares CC BY 4.0 and describes the files as positive
controls used to validate the MetaClean3.0 quality-control method. The recipe
emits only numeric instrument measurements and channel names. It excludes all
FCS text metadata and does not expose participant identities, diagnoses, or
clinical labels.
