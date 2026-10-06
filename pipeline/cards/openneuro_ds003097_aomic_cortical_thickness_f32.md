# AOMIC-ID1000 FreeSurfer 6 Per-Vertex Cortical Thickness Float32

- Candidate id: `openneuro_ds003097_aomic_cortical_thickness_f32`
- Width: float32
- Quantity: Cortical grey-matter thickness in millimetres at every vertex of each hemisphere's white-surface mesh, computed by FreeSurfer 6.0.1 recon-all from 3T T1-weighted MRI (stored as big-endian float32 curv files).
- Source: https://s3.amazonaws.com/openneuro.org/ds003097/derivatives/freesurfer/
- Resources: https://s3.amazonaws.com/openneuro.org?list-type=2&prefix=ds003097/derivatives/freesurfer/&delimiter=/&max-keys=1000, https://s3.amazonaws.com/openneuro.org/ds003097/derivatives/freesurfer/sub-0001/surf/lh.thickness, https://s3.amazonaws.com/openneuro.org/ds003097/derivatives/freesurfer/sub-0001/surf/rh.thickness, https://s3.amazonaws.com/openneuro.org/ds003097/derivatives/freesurfer/sub-0001/scripts/build-stamp.txt, https://s3.amazonaws.com/openneuro.org/ds003097/dataset_description.json
- License: CC0
- License evidence: https://s3.amazonaws.com/openneuro.org/ds003097/dataset_description.json
- License quote: "Name": "AOMIC-ID1000", "BIDSVersion": "1.0.2", "License": "CC0"
- Natural record: One hemisphere's complete surf/{lh,rh}.thickness file for one participant: about 131k-146k per-vertex float32 values (526-584 KB).
- Estimated samples: 400
- Estimated primary values: 54,800,000
- Estimated download bytes: 220,000,000
- Estimated primary bytes: 219,200,000
- Decode path: Pure stdlib FreeSurfer 'new curv' format: 3-byte magic FF FF FF, int32 BE nvertices, int32 BE nfaces, int32 BE values-per-vertex (must be 1), then nvertices big-endian float32. Validate the byte length as 15 + 4*nvertices, convert to little-endian float32, and emit one sample per hemisphere file. The files are uncompressed on S3, so download is about equal to output.
- Novelty kind: new_quantity
- Novelty evidence: novelty.py --url .../ds003097/derivatives/freesurfer/ --terms freesurfer 'cortical thickness' cortex: no registry, ledger or downstream matches. 'cortex' hits only zenodo_npx_opto_templates_f32 and zenodo_open_ephys_continuous_i16 (electrophysiology). No cortical morphometry or FreeSurfer surface material exists locally or downstream. Existing geometry families (modelnet10 mesh vertices, MouseLight neuron trees) are coordinates, not a morphometric scalar field.
- Homogeneity: One FreeSurfer build (freesurfer-Linux-centos6_x86_64-stable-pub-v6.0.1), one scanner protocol and cohort (AOMIC-ID1000; 928 subject directories plus fsaverage), and one quantity and unit (mm, bounded to [0,5] by FreeSurfer's clamp). Left and right hemispheres are the same measurement. Suggest a deterministic subset of about 200 participants x 2 hemispheres.
- Risks: Same OpenNeuro dataset as the DTI-tensor candidate (different pipeline, file and quantity); a judge may weigh the source overlap. FreeSurfer clamps thickness at 5 mm and medial-wall vertices may be 0. Per-sample length varies with mesh size. Vertex order follows the surface tessellation rather than a regular lattice. This is a derived morphometric product (standard published FreeSurfer output).
- Probe evidence: 64 KB range of sub-0001 lh.thickness: magic ffffff, nvertices 131,504, nfaces 263,004, values-per-vertex 1; file size 526,031 = 15 + 4*131,504. The first 16,368 values range from 0.793 to 5.0, with 16,364 distinct and no zeros in that window. HEAD of sub-0002/0300/0928 lh.thickness gave Content-Length 532,439/584,307/560,463. One-byte range GETs of sub-0500 and sub-0928 returned 206. The S3 delimiter listing shows 931 prefixes (928 sub-* plus fsaverage/fsaverage5). build-stamp.txt reports freesurfer v6.0.1. dataset_description.json reports License CC0.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_32bit/scout.20261005_174424.jsonl`).
