# UCI SGEMM GPU Runtime Float32 — staging

This candidate adds GPU kernel-performance measurements from the UCI SGEMM
GPU Kernel Performance dataset. The source is an exhaustive parameter sweep of
OpenCL single-precision matrix-multiplication kernels, with four measured
execution times for every configuration.

The intended primary samples are the four complete runtime columns. Each is a
coherent repetition of the same ordered 241,600-configuration experiment. The
14 integer kernel-tuning parameters remain metadata and are not widened into
the float32 corpus.

UCI publishes the measurements as decimal CSV text, so the representation is
operational rather than native: each finite runtime is rounded once to IEEE-754
binary32 and serialized little-endian.

Run the acquisition and bounded preflight from the repository root:

```bash
bash staging/uci_sgemm_gpu_runtimes_f32/download.sh
```

The script downloads only the official UCI metadata, dataset page, and ZIP. It
checks the CC BY 4.0 statement, ZIP safety, CSV schema, row count, numeric
values, and prospective float32 sample statistics.

Build and independently verify the samples with:

```bash
bash staging/uci_sgemm_gpu_runtimes_f32/build.sh
bash staging/uci_sgemm_gpu_runtimes_f32/verify.sh
```

The pinned result contains four samples of 241,600 values (966,400 bytes)
each, totaling 966,400 float32 values and 3,865,600 bytes. The four samples are
nonconstant and byte-distinct, with roughly 58,000 distinct rounded values per
run. Source decimal values are parsed once, rounded to binary32, and written in
canonical little-endian order.
