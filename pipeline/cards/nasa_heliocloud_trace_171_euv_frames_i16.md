# TRACE (Transition Region and Coronal Explorer) 171 Å Full-Frame 1024x1024 Level-0 EUV CCD Images, Native Int16 DN (HelioCloud SDAC)

- Candidate id: `nasa_heliocloud_trace_171_euv_frames_i16`
- Width: int16
- Quantity: Raw CCD data numbers (12-bit range stored as FITS BITPIX=16, no BZERO) of the solar corona imaged in the Fe IX/X 171 Å EUV passband by TRACE, 0.5 arcsec pixels
- Source: https://gov-nasa-hdrl-data1.s3.amazonaws.com/?list-type=2&delimiter=/&prefix=sdac/trace/
- Resources: https://gov-nasa-hdrl-data1.s3.amazonaws.com/sdac/trace/2003/01/15/trac_171____a0_20030115_002031.fts, https://gov-nasa-hdrl-data1.s3.amazonaws.com/?list-type=2&max-keys=1000&prefix=sdac/trace/2010/05/01/, https://sdowww.lmsal.com/TRACE/Data/DataArchive/dapolicy.htm
- License: TRACE open data policy + NASA SMD open scientific data policy (same rights basis as the accepted nasa_heliocloud_iris_l1_fuv_frames_i16, same bucket)
- License evidence: https://sdowww.lmsal.com/TRACE/Data/DataArchive/dapolicy.htm
- License quote: One feature of the TRACE mission is the open data policy. ... Our fundamental data policy is simple: All TRACE data will be equally available to everyone on the World Wide Web.
- Natural record: One TRACE level-0 FITS image file (trac_171____a0_<date>_<time>.fts or 00171_a* naming after 2007): a single 1024x1024 exposure. Only files of exactly 2,105,280 bytes with NAXIS1=NAXIS2=1024, WAVE_LEN='171', TBIN_CCD=1 are kept.
- Estimated samples: 144
- Estimated primary values: 151,000,000
- Estimated download bytes: 303,000,000
- Estimated primary bytes: 302,000,000
- Decode path: Pure stdlib FITS: read 2880-byte header blocks until END, check SIMPLE/BITPIX=16/NAXIS1/NAXIS2/WAVE_LEN/TBIN_CCD and absence of BZERO/BSCALE (or BZERO=0), then read 1024*1024 big-endian int16 ('>h') and write little-endian int16. Discover files by anonymous S3 ListObjectsV2 per day prefix, filtering on key pattern and Size=2105280. Do not download the 50-400 MB indices/*.csv.
- Novelty kind: new_source
- Measurement type: raw_space_frame
- Instrument line: TRACE EUV telescope CCD (171 Å)
- Archive collection: gov-nasa-hdrl-data1.s3.amazonaws.com/sdac
- Novelty evidence: novelty.py --url sdac/trace/ reports 'same host only' (bucket shared with the accepted IRIS FUV spectrograph and ICON recipes). No TRACE recipe, registry entry or ledger row exists. The only EUV coronal imager in the corpus is SDO/AIA at 32-bit (nasa_sdo_aia_synoptic_i32, downstream sdo_aia_synoptic_stored_pixels_i32). At 16-bit the raw_space_frame members are the IRIS FUV spectrograph, JWST NIRCam ramps, Mastcam-Z, Cassini VIMS and HDAP plates; none is a solar EUV imager.
- Homogeneity: One telescope and CCD (TRACE, amplifier A), one passband (171 Å), one geometry (full 1024x1024, unsummed TBIN_CCD=1, 0.5 arcsec), level-0 DN. Spread over 1998-2010 at ~1 image per month to cover solar-cycle variation. Exposure time varies (AEC), which is natural for the instrument. 195/284/1216/1550/1600/WL frames and binned or partial frames are excluded.
- Risks: Some TRACE frames were JPEG-compressed onboard (lossy DN lattice) and some are AEC-short or partial-FOV frames with large dark areas. The builder should record the onboard compression keyword and keep one compression regime if the header distinguishes it. The 2007+ file naming changed ('00171_a'), so key filters must handle both. Off-limb dark pixels may be numerous but are genuine signal. zlsim may find it close to other 16-bit raw camera frames (IRIS/Mastcam-Z), though coronal EUV morphology differs.
- Probe evidence: S3 ListObjectsV2 for 2003/01/15, 2007/03/10 and 2010/05/01 shows 678, 618 and 769 171 Å files of 2,105,280 bytes (=1024*1024*2 + 8640 header bytes) per day, and 1999/06/15 shows mostly 1550/1600 frames (keep the 171 filter). A 17 KB header range GET shows BITPIX=16, NAXIS1=NAXIS2=1024, WAVE_LEN='171', TBIN_CCD=1, AMP='A', no BZERO. A one-byte range GET on the file returned 206. The LMSAL TRACE data policy page returns 200 with the quoted text.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_16bit/scout.20261009_010213.jsonl`).
