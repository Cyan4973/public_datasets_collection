# NOAA Ship Rainier RICHARD2023L4 Kongsberg EM2040 (launch 2802) Raw .all Seabed-Image (Datagram 'Y', Beam Snippet Backscatter, 0.1 dB) Int16

- Candidate id: `noaa_dcdb_rainier_em2040_seabed_image_i16`
- Width: int16
- Quantity: Per-beam seabed-image backscatter samples from Kongsberg .all datagram 0x59 ('Seabed image data 89'): signed int16 in 0.1 dB steps, typically around -30 to -45 dB. Each ping has about 400 beams and about 8,000 samples. Values are written in file and ping order, beam by beam.
- Source: https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com/index.html
- Resources: https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com/?list-type=2&max-keys=1000&prefix=mb/ships/rainier/RICHARD2023L4/multibeam/data/version1/MB/em2040/, https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com/mb/ships/rainier/RICHARD2023L4/multibeam/data/version1/MB/em2040/0030_20230430_225138_2802.all.mb58, https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com/mb/ships/rainier/RICHARD2023L4/multibeam/data/version1/MB/em2040/0005_20230430_201027_2802.all.mb58
- License: NOAA NODD open data (U.S. Government work; free use, attribution requested)
- License evidence: https://github.com/awslabs/open-data-registry/blob/main/datasets/noaa-dcdb-bathymetry-pds.yaml
- License quote: NOAA data disseminated through NODD are open to the public and can be used as desired. ... NOAA requests attribution for the use or dissemination of unaltered NOAA data.
- Natural record: One raw Kongsberg .all survey-line file (*_2802.all.mb58). The sample is all seabed-image int16 samples from every 'Y' datagram in that file, in ping order. Per-ping records (one Y datagram, about 8,000 values) are a valid alternative but are not recommended: collect at the file boundary.
- Estimated samples: 14
- Estimated primary values: 220,000,000
- Estimated download bytes: 1,020,000,000
- Estimated primary bytes: 440,000,000
- Decode path: Pure stdlib struct, as in the reference probe below. Walk .all datagrams: u32 LE length, STX 0x02, type byte, then the next datagram at +4+len. For type 0x59, header at +2: model u16, date u32, time u32, ping counter u16, serial u16. Then sampling freq f32, range to normal incidence u16, BSn i16, BSo i16, Tx beamwidth u16, TVG crossover u16, Nbeams u16. Then Nbeams × (sorting dir i8, detection info u8, Nsamples u16, centre sample u16), then sum(Nsamples) × int16 LE samples, then a spare/ETX/checksum. Validate ETX 0x03 and the checksum. Emit the int16 samples as-is.
- Novelty kind: new_quantity
- Measurement type: multibeam_seabed_backscatter
- Instrument line: Kongsberg EM2040 multibeam echosounder (NOAA Ship Rainier launch 2802)
- Archive collection: noaa_dcdb_bathymetry_pds
- Novelty evidence: novelty.py --url matched the same host only (the CSB vessel-track f64 recipe, a different prefix and quantity). Term hits are only noaa_wcsd_em302_water_column_i8: a different bucket (noaa-wcsd-pds), sonar (EM302), datagram (.wcd water-column amplitudes) and width. --type multibeam_seabed_backscatter and --archive noaa_dcdb_bathymetry_pds both return 0. The closest 16-bit family is usgs_grandbay_klein3900_sidescan_xtf_u16: linear unsigned side-scan amplitudes from a towed fish, whereas this is signed dB-domain multibeam beam snippets.
- Homogeneity: One sonar (Kongsberg EM2040, system serial 2802 on a Rainier survey launch), one cruise/project (RICHARD2023L4, 2023-04-30), one datagram type and unit (0.1 dB). Exclude the S221 .kmall files in the same folder (different system and format). Sampling frequency (about 20.4 kHz) and the beam count should be checked constant per file; drop files whose model is not 2040.
- Risks: (1) Only 36 .all files exist for this cruise (8.2 GB). A bounded subset of about 14 files (the 12 smallest plus 2 of about 210 MB) gives only about 14 samples. Per-ping samples would give thousands but split the file. (2) The Y fraction of file bytes (about 43%) was measured on one 2 MB prefix and may vary with depth and mode. (3) The 0.1 dB integer lattice gives a smallish alphabet (about 900 distinct values), but values are signed and genuinely 16-bit (range about -900..+50 seen). (4) Large single files (up to 830 MB) must be avoided to stay under cap. (5) The bucket is mostly MB-System derivatives; raw .all exist only for some cruises, so URLs must be pinned with sizes.
- Probe evidence: S3 ListObjectsV2 on the em2040 prefix: 36 *.all.mb58 files, sizes 2,828,052..830,404,164 bytes, total 8.17 GB. A 2 MB range GET of 0030_20230430_225138_2802.all.mb58 parsed cleanly: datagram counts P65 n65 N63 O63 X63 Y63 A7 C7 R5 I1 U1. Y datagrams were 861 KB of the 2 MB. Mid-file Y: model 2040, sf 20424.8 Hz, 400 beams, 7,952 samples, min -898 max 50, first values -363 -420 -429 -371. AWS registry YAML license fetched.

Proposed by the autocollect scout on 2026-10-14 (transcript `.data/pipeline/logs/scout_16bit/scout.20261014_131332.jsonl`).
