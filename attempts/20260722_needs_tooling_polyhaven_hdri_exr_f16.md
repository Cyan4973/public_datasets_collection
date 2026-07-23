# Needs Tooling: polyhaven_hdri_exr_f16 — FLOAT32 PIZ not HALF

- Date: 2026-07-22
- Candidate: `staging/polyhaven_hdri_exr_f16`
- Domain: computer graphics HDR environment lighting probes, CC0
- Intended natural sample: one HDRI channel plane f16 HALF
- Intended primary: `polyhaven_hdri_exr_f16` float16

## Attempt

User ran on 2026-07-22:

```
bash staging/polyhaven_hdri_exr_f16/download.sh   # succeeded: 12 files, 31 MB, 1k EXR
bash staging/polyhaven_hdri_exr_f16/build.sh      # failed: no native 16-bit samples accepted
```

Logs:
- `.data/logs/polyhaven_hdri_exr_f16/download.latest.log` — 12 × 1k EXR via `api.polyhaven.com`
- `.data/logs/polyhaven_hdri_exr_f16/build.latest.log` — `no native 16-bit samples accepted`

Inspection of downloaded headers:

```
python -> exr_header_quick:
abandoned_bakery_1k.exr (4, [('B', 2), ('G', 2), ('R', 2)], ...)  # compression 4=PIZ, type 2=FLOAT
aarfontein_dirt_road_1k.exr (4, [('A',2),('B',2),('G',2),('R',2)], ...)
...
all 1k files = FLOAT32 (type 2) + PIZ (4) or ZIP (3) compression
```

Current local parser `tools/numeric16_extract.py --format exr` only accepts:

- `pixel_type == 1` (HALF) AND
- `compression == 0` (NO_COMPRESSION)

So it correctly rejects these FLOAT + PIZ files.

## Reason

Poly Haven 1k HDRI assets are served as 32-bit float EXR with PIZ/ZIP compression, not native uncompressed HALF. Emitting them as f16 would require float32→float16 conversion, which is derived numeric, not `representation_class=native_numeric`. Also requires a real PIZ/ZIP decompressor (zlib + wavelet) beyond stdlib parser.

## Existing Registry

`attempts/dataset_status.tsv` already lists `polyhaven_hdri_exr_f16` as `deferred` with note about compressed EXR needing tooling. This attempt provides concrete evidence for that deferral.

## Evidence

- Download dir: `.data/downloads/polyhaven_hdri_exr_f16/` — 12 files, e.g., `abandoned_bakery_1k.exr` 1.6 MB
- Header dump shows `type 2 = FLOAT`, `compression 4 = PIZ`
- Build log: `.data/logs/polyhaven_hdri_exr_f16/build.latest.log`

## Classification

`needs_tooling` — needs:

1. OpenEXR decoder supporting PIZ (wavelet+Huffman) and ZIP (zlib) decompression, and
2. Discovery of true HALF assets (type 1) on Poly Haven, e.g., 4k/8k variants may be HALF, or alternative CC0 HDRI source with NONE-compression HALF.

Without those, cannot produce native f16 primary series.

## Retry Condition

Retry only if:

- A real OpenEXR decoder is added as approved local feature (e.g., via `openexr` Python package or bundled C lib), AND
- A bounded set of URLs with proven `pixel_type=HALF` and `sample_format=HALF` is identified, preflighted with header inspection before download.

Alternatively, accept as `f32` dataset (`polyhaven_hdri_exr_f32`) if project decides to allow native float32 HDR, but current hunt is f16.

## Value if Fixed

Would add graphics HDR lighting domain (multi-exposure 360° capture), distinct from ML weight tensors (`hf_smolllm2_135m_safetensors_f16`) despite both being f16.

