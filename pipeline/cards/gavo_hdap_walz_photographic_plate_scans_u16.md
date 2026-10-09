# HDAP Heidelberg Digitized Astronomical Plates: 72 cm Walz Reflector Glass-Plate Scans (1907-1925, Nexscan F4100), Native UInt16 FITS

- Candidate id: `gavo_hdap_walz_photographic_plate_scans_u16`
- Width: uint16
- Quantity: Digitized photographic-plate transmission/density scan value per pixel (scanner DN, 16-bit, stored as BITPIX=16 with BZERO=32768, i.e. native uint16) of historic astronomical glass plates exposed on the Königstuhl 72 cm Walz reflector
- Source: https://dc.g-vo.org/lswscans/res/positions/siap/info
- Resources: https://dc.g-vo.org/tap/sync?REQUEST=doQuery&LANG=ADQL&FORMAT=csv&QUERY=SELECT%20accref,accsize,dateObs%20FROM%20lsw.plates%20WHERE%20instId%20LIKE%20%27%25Walz%25%27%20AND%20accsize%20%3C%2040000000%20ORDER%20BY%20accsize, http://dc.g-vo.org/getproduct/lswscans/data/part2/Walz/FITS/D482.fits, http://dc.g-vo.org/getproduct/lswscans/data/part2/Walz/FITS/D2835.fits
- License: CC0-1.0
- License evidence: https://dc.g-vo.org/oai.xml?verb=GetRecord&metadataPrefix=ivo_vor&identifier=ivo://org.gavo.dc/lswscans/res/positions/siap
- License quote: <rights rightsURI="https://spdx.org/licenses/CC0-1.0.html">To the extent possible under law, the publisher has waived all copyright and related or neighboring rights to the HDAP scans. For details, see the Creative Commons CC0 1.0 Public Domain dedication.
- Natural record: One complete plate-scan FITS image: the full 2-D primary HDU (e.g. D482 is 4145 x 2544 pixels), row-major. One sample per plate.
- Estimated samples: 24
- Estimated primary values: 363,000,000
- Estimated download bytes: 727,000,000
- Estimated primary bytes: 727,000,000
- Decode path: curl each pinned FITS URL (Range is supported, the server answers 206 with the full Content-Range). In Python, read the 2880-byte header cards and check SIMPLE, BITPIX=16, NAXIS=2, BZERO=32768 and BSCALE=1. Then read NAXIS1*NAXIS2 big-endian int16 with struct/array, add 32768 to get uint16, and byteswap to little-endian. Pin sizes from lsw.plates.accsize.
- Novelty kind: new_modality
- Measurement type: photographic_plate_scan
- Instrument line: Heidelberg Nexscan F4100 transmission scans of Königstuhl 72 cm Walz reflector glass plates
- Archive collection: GAVO Heidelberg data centre (dc.g-vo.org) HDAP lswscans
- Novelty evidence: novelty.py --url http://dc.g-vo.org/getproduct/lswscans/ --terms photographic plate heidelberg found no URL match and no plate-scan family in local, registry, ledger or downstream; the only hits were unrelated 'plate' words (force plate, steel plates). novelty.py --type photographic_plate_scan --archive GAVO gave 0 same-type and 0 same-archive. No GAVO/dc.g-vo.org source exists anywhere in the corpus. The bytes are photographic emulsion grain plus density structure (stars, plate edges, handwritten markings) from a flatbed transmission scanner, unlike any CCD/CMOS detector frame family.
- Homogeneity: One telescope (Heidelberg-Königstuhl 72 cm Walz Reflektor, 4,035 plates in the archive), one scanning campaign and scanner (Heidelberg Nexscan F4100, 100 px/mm), one storage convention (BITPIX 16 + BZERO 32768). Keep only Walz plates. 33 Walz plates are under 40 MB (sum 1.035 GB), spanning MJD 17566-24129 (1907-1925). Take about 24 of them for roughly 727 MB, spread across epochs. Do not mix in the Bruce astrograph or Calar Alto plates (different optics and scale, mostly 0.3-1.6 GB each).
- Risks: Choosing plates by file size biases toward smaller plates (the same plate format, just cropped scans); the builder could instead stratify by date within under 60 MB (42 plates). Some plates may carry large blank glass or label areas, so the dominant-value check should be inspected. The server is a university data centre (dc.g-vo.org) and may be slow, so use resumable curl. 24 samples is acceptable but not 50+; the source offers more only at larger sizes.
- Probe evidence: Range GET 0-0 on D482.fits returned 206 with Content-Range: bytes 0-0/21096000. The 14 KB header range showed BITPIX=16, NAXIS1=4145, NAXIS2=2544, BZERO=32768, BSCALE=1, TELESCOP='72cm Walz Reflektor', DATE-OBS 1909-04-03, scanned 2011-06-28. TAP query: lsw.plates holds 19,603 plates; by instrument Walz has 4,035 (21 MB to 452 MB, mean 299 MB). The OAI VOResource record for lswscans/res/positions/siap carries the CC0 rights element.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_225519.jsonl`).
