# Poly Haven Material Roughness Uint8

This staged recipe targets the official 1K grayscale roughness maps for eight
CC0 Poly Haven materials: painted wood, concrete, wallpaper, stone, rusted
metal, bark, sand, and denim. Poly Haven's lossless PNG roughness products are
16-bit, so this width-specific recipe uses the separately published 8-bit JPEG
delivery products and never down-converts the PNGs.

Each 1024×1024 map is one natural two-dimensional sample. Its native uint8
texels encode the PBR microfacet-roughness field. This is materially different
from the accepted uint16 displacement maps for the same surfaces: displacement
describes mesoscopic height, while roughness controls microsurface scattering.

The downloader resolves each exact JPEG from the official asset API, verifies
the official CC0 page, and records size, MD5, SHA-256, and URL. Seven sources
are 8-bit one-component grayscale JPEGs. `concrete_wall_008` is stored with
three components, but its decoded R, G, and B bytes are exactly equal at every
pixel; the recipe checks this invariant and emits the common byte. Decoding
uses the same deterministic, single-threaded FFmpeg path already accepted for
JPEG image families.

Run:

```bash
bash datasets/polyhaven_material_roughness_u8/download.sh
bash datasets/polyhaven_material_roughness_u8/build.sh
bash datasets/polyhaven_material_roughness_u8/verify.sh
```

The eight exact source identities are pinned in `sources.tsv`. The accepted
output contains eight 1024×1024 planes, totaling 8,388,608 values and bytes.
