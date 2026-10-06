# SLAC MeV-UED Sample-Plane Electron-Beam Camera Images (1292x964 full-resolution mode) UInt8

- Candidate id: `zenodo_slac_ued_beam_camera_images_u8`
- Width: uint8
- Quantity: Accelerator beam-diagnostic camera intensities: 8-bit DN images of the relativistic electron bunch at the sample plane of the SLAC MeV ultrafast electron diffraction (UED) beamline, recorded during Bayesian-optimisation scans at 50 fC and 100 fC bunch charge (collimator in).
- Source: https://zenodo.org/records/11095450
- Resources: https://zenodo.org/api/records/11095450/files/UED_MOBO.zip/content
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/11095450
- License quote: Zenodo record 11095450 ('Raw dataset for "Multi-Objective Bayesian Active Learning for MeV-ultrafast electron diffraction"', Ji, Edelen, Roussel, Shen, Miskovich, ...): "license": {"id": "cc-by-4.0"}, access_right "open". Description: "raw data collected at the SLAC MeV-UED facility ... saved in .npy format ... xxxxxxxxxx_qm.npy contains the beam images recorded at the sample plane associated with the spot size".
- Natural record: One beam shot image = one *_qm.npy file. Stored as |u1 shape (3, 964, 1292), but the three planes are byte-identical (verified on 2 files), so a record is one 964x1292 uint8 frame (1,245,488 values).
- Estimated samples: 254
- Estimated primary values: 316,353,952
- Estimated download bytes: 341,298,479
- Estimated primary bytes: 316,353,952
- Decode path: Pure stdlib. Range-read the end of the 2,830,572,986-byte ZIP for the EOCD (2,375 entries, central directory at 2,830,163,105; no ZIP64 needed). Select members spot_size_vs_q_resolution_optimization/Charge_100_fC_col_in/*_qm.npy and Charge_50_fC_col_in/*_qm.npy with uncompressed size 3,736,592 (254 members, 341.3 MB compressed). For each, range-GET local header + compressed data and raw-inflate with zlib.decompressobj(-15). Parse the NPY v1.0 header: magic, then a 2-byte header length, then the dict; assert descr '|u1', fortran_order False, shape (3,964,1292). Assert planes 0, 1 and 2 are identical (skip or flag the file otherwise) and emit plane 0 as a raw uint8 964x1292 sample. Self-test the NPY parser on synthetic files.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url https://zenodo.org/records/11095450 --terms 'electron diffraction', --terms slac, 'beam profile' and 'virtual cathode': no recipe, registry, ledger or downstream match. --terms accelerator matches only zenodo_lecroy_oscilloscope_i16 (16-bit scope traces). No accelerator beam-diagnostic imagery exists locally or downstream at any width. Closest 8-bit relatives are raw camera frames (IUE, Voyager) and EMPIAR SEM slices, which differ in source, physics and noise regime.
- Homogeneity: One camera (sample-plane 'qm' camera), one facility campaign (Aug 2021), one readout mode: full-resolution 1292x964, 254 files in the 100 fC (112) and 50 fC (142) folders. Exclude the 10 fC folder (156 files, 934,244 B: binned 646x482 mode), the THz folder (121 files, 242,192 B: small ROI), and the other cameras (vcc virtual-cathode laser camera, Andor1 int16 diffraction detector, int16 THz streak images). Those are different regimes or widths.
- Risks: Low-signal material. The probed 100 fC frame has mean 9.1 DN, about 47% zeros, all 256 codes used, zlib ratio 0.545, and a faint beam spot only 3-5x the block mean over sensor noise; the judge may call it weak, though it is a genuine detector regime. The triplicated planes must be detected and deduplicated, never emitted 3x. Only one campaign and 254 shots. This is camera-frame material, adjacent to already-represented camera families, so it is lower priority than the other two. Builder must range-fetch members correctly (Zenodo 206 verified).
- Probe evidence: Zenodo API: UED_MOBO.zip 2,830,572,986 B, license cc-by-4.0. The central directory, read via two range GETs, lists 531 qm.npy, 531 vcc.npy, 531 Andor1.npy, 531 scalars.npy and 121 THzon/THzoff npy. qm sizes: 254 x 3,736,592 (full res), 156 x 934,244, 121 x 242,192. Inflated NPY headers: qm '|u1' (3,964,1292); vcc '|u1' (1245488,); Andor1 '<i2' (3,1024,1024); THz '<i2' (1023,1023). Two full-res qm files fetched (~3.1 MB compressed total): planes identical within each file, files differ from each other, values 0-255, and block-sum search shows localized beam features (top 32x32 blocks 2.8-5x the mean). Preview render: dark noisy frame with a faint spot.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_8bit/scout.20261006_011511.jsonl`).
