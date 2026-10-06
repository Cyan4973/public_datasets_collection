# WIOD 2016 Release World Input-Output Tables 2000-2014 (Current Prices, Million US$) Float64

- Candidate id: `wiod2016_world_input_output_tables_f64`
- Width: float64
- Quantity: World input-output flows in millions of US$ at current prices. Rows are 43 countries plus Rest of World × 56 industries (supplying), followed by value-added and summary rows. Columns are the using country-industry intermediate flows (vAUS1..vROW56), final-demand categories by country, and TOT. They are stored natively as Stata doubles: values are RAS-balanced full-precision floats such as 5876.83318062628 and -0.00022121972870081663.
- Source: https://dataverse.nl/dataset.xhtml?persistentId=doi:10.34894/PJ2M1C
- Resources: https://dataverse.nl/api/access/datafile/199103, https://dataverse.nl/api/datasets/:persistentId/?persistentId=doi:10.34894/PJ2M1C, https://www.rug.nl/ggdc/valuechain/wiod/wiod-2016-release
- License: CC-BY-4.0
- License evidence: https://dataverse.nl/api/datasets/:persistentId/?persistentId=doi:10.34894/PJ2M1C
- License quote: DataverseNL dataset termsOfUse: 'The World Input-Output Database (WIOD) is licensed under a Creative Commons Attribution 4.0 International-license.' (links http://creativecommons.org/licenses/by/4.0/)
- Natural record: One year's World Input-Output Table: one member WIOT{YYYY}_October16_ROW.dta per year, 2000-2014, inside WIOTS_in_STATA.zip. Each table is a 2472-row × 2685-double-column matrix, emitted row-major. The string columns (IndustryCode, IndustryDescription, Country) and the RNr/Year columns are auxiliary.
- Estimated samples: 15
- Estimated primary values: 99,559,800
- Estimated download bytes: 638,963,496
- Estimated primary bytes: 796,478,400
- Decode path: curl -L the Dataverse access URL. It 303-redirects to a signed objectstore.surf.nl URL that expires after 1 h; curl -L -C - re-resolves it on resume. Then the stdlib zipfile module (15 deflate members of 55,216,235 B each). Stata release-118 parser: '<release>118</release><byteorder>LSF</byteorder>'; <K> is a u16 (2690); <N> is a u64 (2472); <variable_types> holds K u16 codes (65526=double ×2685, 65529=int, 65530=byte, 7/147/3=strN); fixed-width rows of 21,640 B start after the '<data>' tag. Extract the double columns with struct '<d'. Treat Stata missing doubles (≥ 8.988e307) as missing; none expected. Pure stdlib.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url 'https://dataverse.nl/dataset.xhtml?persistentId=doi:10.34894/PJ2M1C' --terms WIOD input-output 'world input' found no URL, recipe, registry, ledger, downstream or downstream_registry matches. No input-output or national-accounts matrix material exists anywhere in the corpus. The economics material at 64 bits is limited to SEC/Census/EIA tables and indicator series.
- Homogeneity: Every cell is million US$ at current prices, from one release (October/November 2016) and one balancing methodology. The 15 years are the full population of this release's current-price tables. The previous-year-price tables exist only as Excel (WIOTS_PYP_in_EXCEL.zip) and should not be mixed in.
- Risks: (1) Only 15 natural samples, but each is a 6.6M-value matrix, and 15 is the full current-price population. (2) Total ~796 MB is close to the 1 GB cap. The builder may drop the TOT column (a row sum) and the summary rows (II_fob/TXSP/EXP_adj/PURR/PURNR/VA/IntTTM/GO) so derived sums are not counted as primary. That also trims the size. (3) The signed redirect URL expires, so download.sh should re-request the Dataverse URL on retry. (4) The matrix is sparse-ish with many tiny values, which is real structure, not degeneracy.
- Probe evidence: The Dataverse API lists WIOTS_in_STATA.zip (id 199103, 638,963,496 B). A range GET of the last 65 KB parsed the central directory: 15 members WIOT2000..2014_October16_ROW.dta, deflate, 55,216,235 B uncompressed each. A range GET of the first 400 KB decompressed member 1: header release 118, LSF, K=2690, N=2472, type counts {double: 2685, str7, str147, str3, byte, int}. Decoded row 1 is A01 AUS 2000 with values 5876.83318062628, 187.06791866489127, 65.07912176896292 and TOT 28947.95965098717.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_64bit/scout.20261006_012600.jsonl`).
