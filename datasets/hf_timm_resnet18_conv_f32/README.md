# Hugging Face timm ResNet-18 convolution kernels float32 discovery

This candidate targets native float32 convolution weight tensors from
`timm/resnet18.a1_in1k` on the Hugging Face Hub.

Only rank-4 SafeTensors entries are intended as primary samples.  Each sample
preserves one complete convolution kernel bank with axes
`output_channel × input_channel × kernel_y × kernel_x`.  Biases,
normalization parameters, running statistics, and the dense classifier matrix
are excluded.  This differs from the accepted SmolLM2 transformer weights,
whose principal tensors are dense rank-2 projections and embeddings stored at
16 or 8 bits.

Run the metadata-only discovery:

```sh
bash datasets/hf_timm_resnet18_conv_f32/discover.sh
```

The script:

- resolves the exact repository commit through the official Hub API;
- requires `apache-2.0` in both API card metadata and the pinned model card;
- records the exact SafeTensors size and LFS SHA-256;
- range-reads only the SafeTensors header; and
- inventories native `F32`, rank-4 tensors and their shapes without fetching
  tensor payload bytes.

Results are written under `.data/discovery/hf_timm_resnet18_conv_f32/`, with
logs under `.data/logs/hf_timm_resnet18_conv_f32/`.

If the model card does not clearly license the model artifact, or if the
checkpoint is not native float32 SafeTensors with a substantial set of rank-4
kernel banks, the attempt must stop before acquisition.

The successful discovery pinned commit
`491b427b45c94c7fb0e78b5474cc919aff584bbf` and found 20 convolution kernel
banks containing 11,166,912 native float32 values (44,667,648 bytes).  Their
shapes include 1×1, 3×3, and 7×7 spatial kernels, with a median of 147,456
values per natural tensor.

Download and validate the exact 46.8 MB checkpoint with:

```sh
bash datasets/hf_timm_resnet18_conv_f32/download.sh
```

The downloader pins the model card and checkpoint by exact byte size and
SHA-256, reparses the complete SafeTensors container without importing model
code, and checks that every selected F32 tensor is finite and nonconstant.

After download validation succeeds, build and verify locally:

```sh
bash datasets/hf_timm_resnet18_conv_f32/build.sh
bash datasets/hf_timm_resnet18_conv_f32/verify.sh
```
