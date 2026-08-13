# ASWF OpenEXR Scanline HALF Planes

Twenty-seven native float16 channel planes decoded from eight official ASWF
OpenEXR reference images under BSD-3-Clause:

- 24 RGB radiance/color planes: 19,532,736 values, 39,065,472 bytes;
- 3 nonconstant alpha/opacity planes: 2,929,600 values, 5,859,200 bytes.

All sources are ordinary single-part scanline EXRs: six use PIZ and two use
ZIP. Five constant alpha planes and the FLOAT depth channel in `Blobbies.exr`
are excluded. `Cannon.exr` was discovered but is not selected because its B44
compression is outside TinyEXR v1.0.12.

Every source, license document, and provenance document is pinned by Git blob
identity, exact size, and SHA-256. TinyEXR preserves the source HALF type and
the recipe emits canonical little-endian 16-bit words. Verification decodes
all eight sources again and compares all 27 outputs byte-for-byte.

```bash
bash datasets/aswf_openexr_scanlines_f16/download.sh
bash datasets/aswf_openexr_scanlines_f16/build.sh
bash datasets/aswf_openexr_scanlines_f16/verify.sh
```
