# Nanopore RNA004 MinION raw-signal int16

This accepted recipe decodes native signed-int16 raw current traces for
individual Oxford Nanopore direct-RNA reads. The source is Zenodo record
`14676368`, released under CC BY 4.0.

The decoder is the pinned official slow5tools v1.4.0 source tree, built without
HDF5 by its documented Make target. It needs only the existing C/C++ compiler,
GNU Make, zlib, and the vendored StreamVByte submodule; it installs nothing.

Run:

1. `bash datasets/zenodo_nanopore_slow5_i16/prepare_decoder.sh`
2. `bash datasets/zenodo_nanopore_slow5_i16/download.sh`
3. `bash datasets/zenodo_nanopore_slow5_i16/build.sh`
4. `bash datasets/zenodo_nanopore_slow5_i16/verify.sh`

The build emits the longest source-order prefix of complete reads below the
900,000,000-byte primary-output cap. Each read remains a separate
variable-length one-dimensional sample. Verification decodes every selected
record again and compares the emitted little-endian bytes exactly.
