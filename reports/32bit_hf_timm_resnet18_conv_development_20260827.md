# Hugging Face timm ResNet-18 convolution float32 development

## Outcome

Accepted `hf_timm_resnet18_conv_f32` as an AI-adjacent native-float32 family
containing 20 complete rank-4 convolution kernel banks.  The family contributes
11,166,912 values and 44,667,648 bytes, with a median natural tensor size of
147,456 values.

The tensor axes are `output_channel × input_channel × kernel_y × kernel_x`.
The selected layers cover 7×7 input kernels, 3×3 residual-block kernels, and
1×1 downsampling projections.  This is a new geometry relative to the existing
SmolLM2 model families, whose principal learned tensors are transformer
projection and embedding matrices stored as F16/BF16 or Q8_0 codes.

## Source and license

Discovery resolved the public Hugging Face repository
`timm/resnet18.a1_in1k` to commit
`491b427b45c94c7fb0e78b5474cc919aff584bbf`.  Both the Hub API card metadata
and the exact pinned model card declare Apache-2.0.

The 46,807,446-byte `model.safetensors` object is pinned by its Hugging Face LFS
SHA-256, `80c49dee3da4822c009c5a7fe591e9223c5a2cfcf95a4067ca4dfb5a7b89c612`.
The exact 38,416-byte model card is also pinned by SHA-256.  The card identifies
an ImageNet-1k image-classification model; this recipe includes only the
Apache-2.0 model artifact and no source images or labels.

## Numeric validation

The dependency-free parser validates the complete SafeTensors container:

- 10,830-byte JSON header;
- 46,796,608-byte tensor payload;
- 122 non-overlapping tensor spans covering the payload exactly; and
- 20 tensors whose dtype is `F32`, rank is four, and size is at least 1,000
  values.

The selected tensors range from 8,192 through 2,359,296 values.  Every tensor
contains finite, nonconstant learned weights, has at least 8,191 distinct
values in the bounded distinctness check, and contains no exact zero values.
All 20 payload hashes are unique.

## Build and verification

Build copies each selected SafeTensors byte range unchanged into its own raw
sample.  Batch-normalization parameters, running statistics, biases, the dense
classifier matrix, metadata, and container framing are excluded.

Verification independently reparses the complete checkpoint, reconstructs the
same selected tensor inventory and metadata, checks the index and statistics,
and byte-compares every output against its source range.  SafeTensors stores
numeric payloads in little-endian order, so no byte swapping or numerical
conversion is performed.
