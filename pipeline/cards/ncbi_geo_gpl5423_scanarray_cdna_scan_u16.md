# GEO GPL5423 Spruce cDNA Microarray PerkinElmer ScanArray Express Raw Scan Images UInt16

- Candidate id: `ncbi_geo_gpl5423_scanarray_cdna_scan_u16`
- Width: uint16
- Quantity: Raw laser-scanner fluorescence intensity (16-bit DN, 10 um pixels) of spotted Treenomix 21.8K spruce cDNA microarrays: Cy3 or Cy5 channel scans from a PerkinElmer ScanArray Express
- Source: https://ftp.ncbi.nlm.nih.gov/geo/series/GSE23nnn/GSE23678/
- Resources: https://ftp.ncbi.nlm.nih.gov/geo/series/GSE23nnn/GSE23678/suppl/filelist.txt, https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM572nnn/GSM572663/suppl/GSM572663_NK13297011_Cy3_Aug_1_06.tif.gz, https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM572nnn/GSM572664/suppl/GSM572664_NK13293622_Cy5_Aug_1_06.tif.gz, https://ftp.ncbi.nlm.nih.gov/geo/series/GSE22nnn/GSE22924/suppl/filelist.txt
- License: NCBI public data: unrestricted (precedent: accepted ncbi_refseq_viral_genomes_u8, LicenseRef-NCBI-Public-Data)
- License evidence: https://ftp.ncbi.nlm.nih.gov/README.ftp
- License quote: NOTE: ALL DATA HERE IS PUBLIC, NON-SENSITIVE, UNRESTRICTED SCIENTIFIC DATA SHARING AMONG SCIENTIFIC COMMUNITIES. THESE SERVERS ARE INTENTIONALLY PUBLIC.
- Natural record: One single-channel scan TIFF (one hybridization x one dye), e.g. GSM572663_..._Cy3_Aug_1_06.tif.gz. It is one uncompressed 16-bit grayscale page of 2200 x ~7000 pixels (about 15.4M values). Emit the whole raster and do not tile.
- Estimated samples: 12
- Estimated primary values: 186,000,000
- Estimated download bytes: 293,925,867
- Estimated primary bytes: 372,000,000
- Decode path: curl the per-sample .tif.gz (names and sizes pinned from filelist.txt), then gunzip. Parse the TIFF: 'II', 42, IFD0. Check W=2200, Bits=16, Compression=1, Photometric=1, SPP=1, RowsPerStrip=1, single page (next IFD 0). Read the StripOffsets/StripByteCounts arrays and concatenate strips into a little-endian uint16 raster. Pure stdlib (gzip, struct).
- Novelty kind: new_source
- Novelty evidence: novelty.py --url on the GSE23678 dir: same-host-only (non-microarray NCBI recipes). Terms 'scanarray', 'microarray', 'gpl5423' and 'ftp.ncbi.nlm.nih.gov/geo' gave no matches anywhere. The existing u16 fluorescence material is cell microscopy (BBBC021/039). A microarray laser-scanner raster is a different instrument class with a regular spot-lattice structure, saturated spots and slide background.
- Homogeneity: One platform (GPL5423 Treenomix 21.8K spruce cDNA array), one lab, one scanner model (PerkinElmer ScanArray Express, protocol 'Easy Scan', 10 um), one series (GSE23678, 36 hybridizations x Cy3/Cy5 = 72 TIFFs). Cy3 and Cy5 scans share unit and process. Sibling series GSE22924 (pine, same platform and scanner, 6985-row scans) is available if more samples are wanted. Plant tissue only: no personal data.
- Risks: (1) Rights: same GEO/NCBI basis and caveat as the IDAT candidate (GEO disclaimer page proxy-blocked here). (2) Samples are large (~31 MB each), so 12 samples is about 372 MB primary. The builder may take 8-20 files depending on the judge's sample-count preference; the full series (72 files) would be ~2.2 GB, over the cap. (3) Scan height varies slightly (7056 vs 6985 rows seen), so don't assume a fixed shape. (4) Bright spots saturate at 65535; keep them as native values. (5) 2006-era scans; confirm every selected file's Make/Model/Software tags match before acceptance.
- Probe evidence: E-utilities: TIFF[Supplementary Files] AND expression profiling by array returned 351 series. GSE23678 = 36 samples, GPL5423 ('Treenomix spruce 21.8K cDNA microarray', 381 samples platform-wide). Its filelist.txt lists 72 TIFF.gz, 23.2-25.6 MB each (1.75 GB); the first 6 GSMs = 12 files = 293,925,867 B. One-byte -L range GETs on GSM572664 Cy5 returned 206. Partial gunzip of the first 128-256 KB gave TIFF II/42, W=2200, H=7056 (GSE22924: 6985), 16 bits, Compression 1, SPP 1, 1 row per strip, Make 'PerkinElmer', Model 'Express 430723', Software 'ScanArray Express, Microarray Analysis System 2.1.0.0', DateTime 2006:08:01, next IFD 0. The top-edge rows in the probe: min 27, median 316, p99 2050, max 65535, 2,464 distinct values.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_16bit/scout.20261005_180613.jsonl`).
