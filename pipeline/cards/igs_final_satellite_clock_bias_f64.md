# IGS Final Combined GPS Satellite Clock Biases (30 s RINEX CLK, 2024 H1) Float64

- Candidate id: `igs_final_satellite_clock_bias_f64`
- Width: float64
- Quantity: Estimated GPS satellite clock offsets in seconds from IGS final combined clock products (RINEX 3.00 clock 'AS' records, 30-s sampling). Values are printed as %19.12E with 12-13 significant digits, e.g. 1.682124842910e-04.
- Source: https://igs.bkg.bund.de/root_ftp/IGS/products/
- Resources: https://igs.bkg.bund.de/root_ftp/IGS/products/2295/IGS0OPSFIN_20240010000_01D_30S_CLK.CLK.gz, https://igs.bkg.bund.de/root_ftp/IGS/products/2300/IGS0OPSFIN_20240350000_01D_30S_CLK.CLK.gz, https://igs.bkg.bund.de/root_ftp/IGS/products/2321/, https://mgex.igs.org/wp-content/uploads/2020/09/IGS-Data-and-Product-Disclaimer-and-Terms-of-Use-200805.pdf
- License: IGS Data and Product Terms of Use (open, unrestricted use including commercial, with attribution)
- License evidence: https://mgex.igs.org/wp-content/uploads/2020/09/IGS-Data-and-Product-Disclaimer-and-Terms-of-Use-200805.pdf
- License quote: The IGS products and station data are provided openly for the benefit of all scientific, educational, and commercial users. For 25 years, IGS data and products have been made openly available for use without restriction, and continue to be offered free of cost or obligation. ... By accessing data, products, and any other information from the IGS, users agree to appropriately cite and attribute these resources
- Natural record: One daily IGS0OPSFIN 30S CLK file. The sample is all 'AS' (satellite) clock-bias values in file order (about 31-32 GPS satellites x 2,880 epochs, about 92k values). Alternatively the builder can emit one series per satellite-day (2,880 values). Sigma values and 'AR' receiver clocks stay auxiliary or excluded.
- Estimated samples: 182
- Estimated primary values: 16,250,000
- Estimated download bytes: 455,000,000
- Estimated primary bytes: 130,000,000
- Decode path: Pure stdlib: gzip.decompress, then skip to 'END OF HEADER'. For lines starting with 'AS ', fields are type, PRN, Y M D h m s, nvalues, bias, [sigma]; parse the bias with float() to struct '<d'. Pin the file list as 2024-001..2024-182 (GPS weeks 2295-2321) with sizes and hashes. Validate per-file epoch count (2,880) and PRN set.
- Novelty kind: new_quantity
- Novelty evidence: novelty.py on the BKG IGS products URL: no URL matches. Terms (igs/clock/gnss) match only noaa_cors_* RINEX observation families (pseudorange/carrier phase/SNR from station receivers, a different file type and quantity) and unrelated tokens. No registry or ledger rows for IGS products or clocks.
- Homogeneity: One product line (IGS final combined, IGST-aligned GPS satellite clocks), one quantity (clock offset, seconds), uniform 30-s lattice, one analysis process (weighted combination of ESA/GFZ/GRG clocks). Receiver ('AR') clocks are a different regime and are excluded. Six months (182 days) gives about 130 MB of primary output.
- Risks: The license is the IGS Terms of Use ('use without restriction' plus attribution) rather than a named CC license; a strict judge may want a formal license. Values are decimal text with about 12 significant digits (genuinely beyond float32, with the noaa_cors precedent). Satellite clock series contain large per-PRN offsets plus drift; per-file samples interleave satellites epoch-major. Occasional satellite outages reduce per-file counts.
- Probe evidence: BKG directory listings for weeks 2295, 2300 and 2321 show IGS0OPSFIN_2024DDD0000_01D_30S_CLK.CLK.gz (about 2.4-2.5 MB each). A one-byte range GET returned 206. Range-fetched a 200 KB gzip prefix of 2024-035 and stream-decompressed it: RINEX 3.00 C header ('THE COMBINED CLOCKS ARE A WEIGHTED AVERAGE OF: esa gfz grg', aligned to IGST), 130 header lines, then 'AS G01 2024 02 04 00 00 0.000000 2 1.682124842910e-04 1.572715944760e-11'. The prefix holds 7,040 AS and 2,454 AR records. IGS terms PDF fetched (5 Aug 2020).

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_64bit/scout.20261005_215706.jsonl`).
