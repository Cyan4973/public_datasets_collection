# ESA IGS Analysis-Centre Final Daily GNSS Solution SINEX Normal-Equation Matrices (SOLUTION/NORMAL_EQUATION_MATRIX L), 2024 Q1, Float64

- Candidate id: `esa_igs_final_daily_sinex_normal_equations_f64`
- Width: float64
- Quantity: Lower-triangular normal-equation matrix (N = AᵀPA) of ESA/ESOC's daily final GNSS network solution. Parameters: about 150 stations' XYZ, about 79 GNSS satellite antenna offsets, and pole/UT1/LOD Earth-orientation terms (693 parameters on 2024-02-04, giving 240,471 entries). Values are printed in SINEX E-notation with 15 significant digits.
- Source: http://navigation-office.esa.int/products/gnss-products/
- Resources: http://navigation-office.esa.int/products/gnss-products/2300/ESA0OPSFIN_20240350000_01D_01D_SOL.SNX.gz, http://navigation-office.esa.int/products/gnss-products/2310/ESA0OPSFIN_20241050000_01D_01D_SOL.SNX.gz, https://igs.bkg.bund.de/root_ftp/IGS/products/
- License: IGS Data and Product Terms of Use (open, use without restriction, attribution requested); same LicenseRef as the accepted igs_final_satellite_clock_bias_f64. ESA's Navigation Support Office also states the products are freely available.
- License evidence: https://igs.org/wp-content/uploads/2020/09/IGS-Data-and-Product-Disclaimer-and-Terms-of-Use-200805.pdf
- License quote: 'The IGS products and station data are provided openly for the benefit of all scientific, educational, and commercial users. For 25 years, IGS data and products have been made openly available for use without restriction, and continue to be offered free of cost or obligation.' (IGS Terms of Use 2020-08-05). ESA NSO GNSS_based_products.html: 'Our latest published products are freely available on our web page', listing 'IGS AC ESA Finals ... SINEX'.
- Natural record: One daily ESA0OPSFIN_YYYYDDD0000_01D_01D_SOL.SNX.gz solution. The sample is its complete NORMAL_EQUATION_MATRIX L lower triangle in row-major order. Blank entries are zero per the SINEX spec, but the probed file was fully dense with 0 zeros.
- Estimated samples: 91
- Estimated primary values: 21,880,000
- Estimated download bytes: 225,000,000
- Estimated primary bytes: 175,000,000
- Decode path: curl the .SNX.gz files (2.4-2.5 MB each). Python gzip, then line-parse between '+SOLUTION/NORMAL_EQUATION_MATRIX L' and '-SOLUTION/NORMAL_EQUATION_MATRIX L': fields are PARA1 PARA2 then up to 3 E-format values for columns PARA2..PARA2+2. Fill an n(n+1)/2 lower triangle, with n taken from SOLUTION/ESTIMATE (or the max index) and checked against it. Write little-endian struct '<d'. Optionally emit the NORMAL_EQUATION_VECTOR as an auxiliary series. Pure stdlib.
- Novelty kind: new_quantity
- Measurement type: geodetic_normal_equations
- Instrument line: esa_esoc_igs_ac_final_daily_gnss_network_solution
- Archive collection: navigation-office.esa.int/products/gnss-products
- Novelty evidence: novelty.py --url http://navigation-office.esa.int/products/gnss-products/ --terms sinex 'normal equation': no URL, recipe, registry, ledger or downstream matches. The vocabulary has no geodetic normal-equation or covariance type. The nearest are gnss_clock (igs clock bias, a different product file) and sparse_matrix_entries (NIST Matrix Market). This is a dense, symmetric, physically weighted geodetic design product, not a sparse test matrix.
- Homogeneity: One product line (ESA AC final daily SINEX 2.02), one block type (NEQ L), one generation process (ESA NAPEOS daily network LSQ) and a fixed calendar window. Parameter count varies a little day to day with station and satellite availability, so sample sizes vary; that is natural. Entries span many magnitudes because parameter units differ (m for STAX/SATA, mas and ms for EOPs). That is intrinsic to one NEQ object, so do not split it by parameter block.
- Risks: Rights: the clearest grant is the IGS Terms of Use. ESA's server says only 'freely available'. Prefer the identical file from the IGS Global Data Center at BKG (root_ftp/IGS/products/WWWW/), which was unreachable (proxy 503 / http 000) during probing. Use ESA as a fallback and record which host was used. BKG would become a second acceptance from that host this effort (the clock-bias recipe is the first). Older weeks may carry COVA instead of NEQ, so verify the block type per file. The NEQ block is about 80k lines per file, so parsing is slow-ish but fine.
- Probe evidence: Downloaded one 2.4 MB file (ESA0OPSFIN_20240350000_01D_01D_SOL.SNX.gz). '%=SNX 2.02 ESA ... P 00693'. Blocks: SOLUTION/ESTIMATE (150 STAX/Y/Z, 79 SATA_X/Y/Z, XPO, YPO, XPOR, YPOR, UT, LOD) and SOLUTION/NORMAL_EQUATION_MATRIX L on lines 3661-84051, totalling 240,471 values (= 693*694/2) with 0 zeros. Sample line: '3 1 0.155941396348824E+05 -.115786836202573E+01 0.526904070603480E+05'. Weeks 2295, 2310 and 2320 each list 7 daily SOL.SNX.gz files. Range GET on ESA0OPSFIN_20241050000_01D_01D_SOL.SNX.gz returned 206 (1 byte); HEAD gave Content-Length 2475153.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_64bit/scout.20261008_162656.jsonl`).
