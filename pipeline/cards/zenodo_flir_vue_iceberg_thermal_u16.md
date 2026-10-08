# Drone Thermal-Infrared Imagery of a Drifting Iceberg, NE Greenland 2018 (FLIR Vue Pro R 640 Radiometric TIFF Frames), UInt16

- Candidate id: `zenodo_flir_vue_iceberg_thermal_u16`
- Width: uint16
- Quantity: Radiometric longwave-infrared (7.5-13.5 um) microbolometer raw counts from a FLIR Vue Pro R 640 camera on a DJI Phantom 3, imaging an iceberg and the surrounding seawater at 1 s intervals.
- Source: https://zenodo.org/records/10641368
- Resources: https://zenodo.org/records/10641368/files/20180820_035505.zip, https://zenodo.org/records/10641368/files/20180820_040000.zip, https://zenodo.org/records/10641368/files/20180821_034534.zip, https://zenodo.org/records/10641368/files/20180821_092823.zip, https://zenodo.org/records/10641368/files/20180821_155204.zip, https://zenodo.org/records/10641368/files/20180821_160000.zip
- License: CC BY 4.0
- License evidence: https://zenodo.org/api/records/10641368
- License quote: metadata.license = {'id': 'cc-by-4.0'}; description: 'This dataset contains raw thermal infrared (TIR) imagery ... Each .zip file contains .tiff images as produced by the camera and stored on the SD card.'
- Natural record: One camera frame: a 640x512 single-channel uncompressed 16-bit TIFF (655,360 uint16 values, about 1.3 MB).
- Estimated samples: 450
- Estimated primary values: 295,000,000
- Estimated download bytes: 120,000,000
- Estimated primary bytes: 590,000,000
- Decode path: curl a range GET of each zip's central directory (members are deflated, about 220-350 KB each). Select every ~10th frame in time order per flight session, then range-GET just those local members (or download the zips whole: 1.14 GB total). Python zlib raw-inflates each member. Parse the TIFF IFD (BitsPerSample 16, Compression 1, one strip of 655,360 bytes at offset 8), read the little-endian uint16 strip, and emit it unchanged.
- Novelty kind: new_modality
- Measurement type: thermal_camera_image
- Instrument line: flir_vue_pro_r_640_microbolometer
- Archive collection: zenodo.org
- Novelty evidence: novelty.py --url zenodo.org/records/10641368 --terms iceberg 'FLIR Vue' thermal: no recipe or ledger match for this record. Registry: zenodo_radiometric_thermal_u16 is blocked with retry_condition 'Retry only with an exact permissively licensed archive or direct source known to contain single-channel native-16-bit thermal frames'. This record satisfies that condition: native 16-bit single-channel frames inside ZIPs, verified by IFD decode. Thermal at 16 bits exists only from orbit (ASTER TIR, GOES C13), which are scene-scale radiometer DN, not uncooled microbolometer camera frames.
- Homogeneity: One camera (FLIR Vue Pro R 640, 13 mm), one platform, one campaign (Dickson Fjord, 20-21 Aug 2018), one format (640x512 uint16 radiometric TIFF). Six flight sessions share the same settings. Temporal subsampling avoids near-duplicate consecutive 1 Hz frames without mixing regimes.
- Risks: (1) Low-contrast ocean/ice scenes may be highly compressible and could sit close to ASTER TIR statistically; the zlsim gate decides. (2) Consecutive frames are highly correlated, so the builder should subsample. (3) This is a single campaign with 6 sessions; sample count is ample, but scene diversity is moderate. (4) FLIR EXIF/maker-note metadata (Planck constants) is auxiliary only.
- Probe evidence: HEAD 20180820_035505.zip: 200, 70,929,301 bytes. A tail range GET parsed 296 central-directory entries (deflated .tiff members, 659,915 bytes uncompressed each). A range GET of the first member (221 KB), raw-inflated, gave TIFF IFD: 256=640, 257=512, 258=16, 259=1 (uncompressed), 262=1 (min-is-black), 277=1, 279=655,360, Make string present. The Zenodo API lists 6 zips totalling about 1.135 GB, licence cc-by-4.0.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_163746.jsonl`).
