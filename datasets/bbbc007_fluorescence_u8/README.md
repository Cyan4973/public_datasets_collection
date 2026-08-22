# BBBC007 Microscopy Uint8

This staged recipe targets the native 8-bit microscopy images in Broad
Bioimage Benchmark Collection image set BBBC007. The source contains measured
Drosophila Kc167 cell imagery with varied acquisition/rendering encodings:
single-channel PackBits TIFFs and interleaved RGB TIFFs.

Each decoded source image plane is one natural two-dimensional sample. Exact
duplicate planes within the source are retained only once so that RGB storage
redundancy does not overweight identical pixels. TIFF headers, strip framing,
compression codes, filenames, and annotations are not sample bytes.

This is a width-correct follow-up to the recorded
`bbbc007_microscopy_tiff_u16` failure. That attempt established that these
TIFFs are 8-bit, not 16-bit; it did not reject them as uint8 material.

Run:

```bash
bash staging/bbbc007_fluorescence_u8/download.sh
bash staging/bbbc007_fluorescence_u8/build.sh
bash staging/bbbc007_fluorescence_u8/verify.sh
```

The official BBBC007 page explicitly applies a CC0 waiver to the Drosophila
Kc167 images and ground truth. The recipe pins that page as rights evidence.
The accepted output contains 45 unique planes and 8,050,720 uint8 values.
