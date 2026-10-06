# Fingrid Nordic Synchronous-Area Power-Grid Frequency 10 Hz Measurements (daily records) Float32

- Candidate id: `fingrid_nordic_grid_frequency_10hz_f32`
- Width: float32
- Quantity: Electrical frequency (Hz) of the Nordic synchronous power system, measured at Fingrid 400 kV substations in Finland at 10 samples per second.
- Source: https://data.fingrid.fi/en/datasets/339
- Resources: https://data.fingrid.fi/files/339/2024/2024-01.7z, https://data.fingrid.fi/files/339/2024/2024-07.7z, https://data.fingrid.fi/files/339/2025/2025-01.7z
- License: CC-BY-4.0
- License evidence: https://data.fingrid.fi/en/datasets/339
- License quote: Dataset page 'Frequency - historical data': 'License: Creative Commons Attribution', linked to https://creativecommons.org/licenses/by/4.0/. Description: 'Frequency of the Nordic synchronous system with a 10 Hz sample rate... divided into archives consisting of monthly frequency measurement data. Within the archives, the data is divided into daily CSV-files.'
- Natural record: One daily CSV inside a monthly 7z archive (e.g. Taajuusdata2024-01-01.csv; 'Time,Value'; 864,000 rows for a full day). Emit Value as a float32 series.
- Estimated samples: 62
- Estimated primary values: 53,600,000
- Estimated download bytes: 131,333,849
- Estimated primary bytes: 214,000,000
- Decode path: Option 1: bsdtar -xf (local libarchive 3.5.3 with liblzma 5.2.5 reads 7z). Option 2: pure stdlib. Parse the 7z start header and the encoded header (LZMA1 props 5d00100000), decode the real header with lzma FORMAT_RAW, then stream-decode the solid LZMA2 data (dict prop 0x18 = 16 MiB) with lzma.LZMADecompressor(FORMAT_RAW, [{'id': FILTER_LZMA2}]) and split by substream sizes. Then csv, struct '<f'. Values have at most 5 decimals near 50 Hz; float32 ulp there is 3.8e-6, below the half-step of 5e-6, so the printed decimals round-trip exactly.
- Novelty kind: new_quantity
- Novelty evidence: novelty.py --url https://data.fingrid.fi/files/339/2024/2024-01.7z --terms fingrid 'grid frequency' taajuus nordic: no matches in recipes, registry, ledger, downstream or downstream_registry. The registry has no Fingrid or grid-frequency rows. Local electricity families (household_power_uci, electricity_load_diagrams_uci) are consumption, not system frequency.
- Homogeneity: One quantity, one TSO measurement system, one 10 Hz cadence. Use non-DST-transition months (e.g. January and July) so every day is a full 864,000-row record. Don't mix in Fingrid's 3-minute real-time frequency product.
- Risks: Narrow dynamic range (about 49.8-50.2 Hz), so the high bits carry low entropy, though the material is genuine. Telecom gaps can drop rows; define a gap policy and report row counts. Timestamps are Finnish local time. Older archives (2015/2020 paths) returned 404, and the page lists 2023-2026. The 7z solid archive must be fetched whole per month. The open-data API needs a key, but the /files/ downloads are anonymous.
- Probe evidence: HEAD 2024-01.7z 64,898,861 B (accept-ranges bytes, last-modified 2024-04-17); 2024-07.7z 66,434,988 B; 2025-01.7z 66,380,610 B; 1-byte range GET returned 206. Decoded the encoded 7z header: 31 entries Taajuusdata2024-01-01.csv ... -31.csv. LZMA2-decoded the first 3 MB: 'Time,Value', '2024-01-01 00:00:00.000,50.01067', '...00:00:00.100,50.01055'. 13,594 distinct values over 89,580 rows, range 49.884-50.074.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_32bit/scout.20261005_234311.jsonl`).
