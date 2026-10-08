# ambientCG Photogrammetry PBR Materials: Tangent-Space Normal Maps (NormalGL, 16-bit PNG, RGB) UInt16

- Candidate id: `ambientcg_photogrammetry_normalgl_u16`
- Width: uint16
- Quantity: Tangent-space surface normal vectors encoded as 16-bit unsigned per channel (R,G,B = X,Y,Z mapped to 0..65535, OpenGL Y-up convention), for real-world surfaces captured with height-field photogrammetry.
- Source: https://ambientcg.com/list?type=Material
- Resources: https://ambientcg.com/api/v2/full_json?type=Material&limit=2000&include=downloadData, https://ambientcg.com/get?file=Wood096_1K-PNG.zip, https://acg-download.struffelproductions.com/file/ambientCG-Web/download/Wood096_0WgvcsZ3/Wood096_1K-PNG.zip
- License: CC0 1.0 Universal
- License evidence: https://docs.ambientcg.com/license/
- License quote: All ambientCG assets are provided under the Creative Commons CC0 1.0 Universal License. This applies to the downloadable asset files and the material preview renders shown for each asset on the site.
- Natural record: One material's 1K NormalGL texture (<id>_1K-PNG_NormalGL.png): 1024x1024 RGB, 3,145,728 uint16 values (about 6.3 MB) per sample. The constant alpha plane is stripped.
- Estimated samples: 110
- Estimated primary values: 346,000,000
- Estimated download bytes: 560,000,000
- Estimated primary bytes: 692,000,000
- Decode path: The ambientCG v2 API lists materials with creationMethod. Keep creationMethod == 'PBRPhotogrammetry' (356 assets) and take a deterministic subset. The 1K-PNG zips are STORED (method 0), so curl range-GETs only the NormalGL member (about 5 MB) using the central directory from a small tail GET. Decode with the repo's pure-stdlib 16-bit PNG decoder (zlib plus scanline unfilter, big-endian to little-endian; see the tum_rgbd/polyhaven displacement recipes), extended to colour type 6. Verify alpha is constant 65535 and drop it. Emit interleaved RGB uint16 little-endian.
- Novelty kind: new_quantity
- Measurement type: pbr_texture_map
- Instrument line: ambientcg_heightfield_photogrammetry
- Archive collection: ambientcg.com
- Novelty evidence: novelty.py --url ambientcg.com --terms ambientcg 'normal map' NormalGL: no matches. pbr_texture_map exists at 16 only as single-channel displacement heightfields (polyhaven_material_displacement_png_u16) and at 8 as roughness. A 3-channel interleaved unit-vector normal map centred at 32768 is a different quantity with different channel correlation, and it comes from a new source (ambientCG, not Poly Haven).
- Homogeneity: One creation method (photogrammetry only; exclude the 1405 PBRProcedural Substance assets, 202 approximated and 37 multi-angle), one map type (NormalGL, not DX), one resolution (1K), one encoding (16-bit PNG). Categories (wood, rock, ground, fabric...) share the same encoding and process.
- Risks: (1) Possible compression similarity to the Poly Haven displacement family. Normals are derivatives of height, so their statistics differ, but the zlsim gate decides. (2) The 1K maps are ambientCG's downsampled published products. 2K could be used instead with fewer samples. (3) The download host redirects to a Backblaze CDN with an asset-specific path, so the recipe must follow redirects and pin sizes. (4) Builder must confirm that the 16-bit depth holds across the photogrammetry subset (checked on one asset).
- Probe evidence: The API reports 2014 materials (creationMethod counts: PBRProcedural 1405, PBRPhotogrammetry 356, PBRApproximated 202, PBRMultiAngle 37). The Wood096_1K-PNG.zip download link 302-redirects to acg-download.struffelproductions.com: 200, Content-Length 15,153,371, Accept-Ranges bytes. A tail central-directory read shows all members stored. Range reads of the member headers gave the IHDR: NormalGL 1024x1024 bit depth 16, colour type 6. NormalDX is the same. Displacement is 16-bit grey. The license page was fetched.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_163746.jsonl`).
