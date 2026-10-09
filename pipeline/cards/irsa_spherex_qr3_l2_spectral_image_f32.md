# SPHEREx Quick Release 3 Level-2 Calibrated Spectral Images (Detector 1, 0.75-1.1 um Linear-Variable-Filter), IMAGE Extension MJy/sr, Native Float32

- Candidate id: `irsa_spherex_qr3_l2_spectral_image_f32`
- Width: float32
- Quantity: Calibrated near-infrared sky surface brightness (MJy/sr) per pixel of a 2040x2040 HgCdTe detector behind a linear variable filter (wavelength varies across the array)
- Source: https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/qr3/level2/
- Resources: https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/qr3/level2/2026W30_1B/l2b-v27-2026-222/1/level2_2026W30_1B_0001_1D1_spx_l2b-v27-2026-222.fits, https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/?list-type=2&delimiter=/&prefix=qr3/level2/, https://irsa.ipac.caltech.edu/Missions/spherex.html, https://science.data.nasa.gov/about/license
- License: CC0 1.0 (NASA Science Data license for NASA-led missions; SPHEREx is a NASA MIDEX mission run by JPL/Caltech)
- License evidence: https://science.data.nasa.gov/about/license
- License quote: Unless the data file is marked with a restrictive notice or license, data that is provided from a NASA-led mission including observations, engineering, calibration, and auxiliary data are licensed as Creative Commons Zero. There are no restrictions on the usage of these data.
- Natural record: One L2 spectral-image exposure's IMAGE extension: 2040x2040 float32 (4,161,600 values)
- Estimated samples: 30
- Estimated primary values: 124,848,000
- Estimated download bytes: 500,000,000
- Estimated primary bytes: 499,392,000
- Decode path: FITS: PRIMARY (empty) + IMAGE HDU uncompressed BITPIX=-32 2040x2040 BUNIT 'MJy / sr' starting at byte 2880 (header) -> data 5760..16,652,160. download.sh can range-GET only the first ~16.7 MB of each 66 MB file (S3 supports Range); validate header cards; struct '>f' -> little-endian float32. FLAGS (RICE) / VARIANCE / ZODI / EPSF are not needed.
- Novelty kind: new_source
- Measurement type: calibrated_sky_image
- Instrument line: spherex_lvf_hgcdte
- Archive collection: nasa-irsa-spherex.s3/qr3/level2
- Novelty evidence: novelty.py --url nasa-irsa-spherex / --terms: no matches. No calibrated astronomical sky-image family at 32-bit: raw_space_frame members are raw single-read DN frames (IUE u8, IRIS i16, Voyager u8, JWST ramps u16) plus the tiny nasa_fits_sample_image_planes set. --type calibrated_sky_image: 0; --archive nasa-irsa-spherex: 0. IRSA has no prior acceptance.
- Homogeneity: One detector (DetID 1, SWIR band 1) only, one pipeline release (qr3, l2b-v27) and one extension (IMAGE); exposures drawn across the ~10 QR3 week groups for sky diversity. Do not mix the six detectors (different bands and zodiacal backgrounds).
- Risks: Quick-release (QR) products are preliminary calibration, so pin exact keys and version strings. Bucket is us-east-1 (us-west-2 endpoint redirects). Bad pixels may be NaN or flagged rather than NaN; build and verify need a consistent policy. A WISE or other IR-image family accepted later could sit close to this one.
- Probe evidence: S3 ListObjectsV2 200 OK: qr3/level2 holds 10 week-group prefixes; one group lists >=329 D1 frames of ~66 MB each. HDU walk by range GET: IMAGE BITPIX=-32 [2040,2040] BUNIT 'MJy / sr' at offset 2880, FLAGS RICE_1, VARIANCE -32, ZODI -32, EPSF, WCS-WAVE. Header DETECTOR=1 ('1-3: SWIR, 4-6: MWIR'). IRSA SPHEREx page 200 (QR3 released September 2026).

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_164906.jsonl`).
