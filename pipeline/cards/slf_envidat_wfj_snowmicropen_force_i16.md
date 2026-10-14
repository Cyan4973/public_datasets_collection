# SLF WFJ_DailySMP Weissfluhjoch (Davos) Daily SnowMicroPen Snow-Penetration Force Profiles, Device S36M 2015-2020, Native Int16 ADC Counts (.PNT)

- Candidate id: `slf_envidat_wfj_snowmicropen_force_i16`
- Width: int16
- Quantity: Raw penetration-force ADC counts from the SnowMicroPen's piezo force sensor, recorded about every 4 µm of depth as the tip is driven through the snowpack. These are native big-endian 16-bit integers; the PNT header holds the force conversion factor.
- Source: https://www.envidat.ch/#/metadata/wfj_dailysmp
- Resources: https://zhc-c.s3.cloud.switch.ch/envidat-doi/10.16904_envidat.641/data/raw_data.zip, https://zhc-c.s3.cloud.switch.ch/envidat-doi/10.16904_envidat.641/data/raw_data.csv, https://zhc-c.s3.cloud.switch.ch/envidat-doi/10.16904_envidat.641/data/Readme.pdf, https://www.envidat.ch/api/action/package_show?id=wfj_dailysmp
- License: CC-BY-SA-4.0 (EnviDat dataset license: Creative Commons Attribution Share-Alike). An MIT LICENSE file also sits in the data folder; both are permissive.
- License evidence: https://www.envidat.ch/api/action/package_show?id=wfj_dailysmp
- License quote: license_id: "cc-by-sa", license_title: "Creative Commons Attribution Share-Alike (CC-BY-SA)". The data folder's LICENSE file reads: "MIT License Copyright (c) 2025 WSL Institute for Snow and Avalanche Research SLF Permission is hereby granted, free of charge..."
- Natural record: One SMP penetration profile, i.e. one .PNT file = one vertical force profile through the snowpack. The bounded scope is every BestOfDay=1 profile from device S36M (winters 2015/16-2019/20), 478 profiles listed in raw_data.csv.
- Estimated samples: 478
- Estimated primary values: 160,000,000
- Estimated download bytes: 215,000,000
- Estimated primary bytes: 320,000,000
- Decode path: curl the 1.6 MB zip central directory (EOCD at file end: 16,535 entries, CD offset 3,132,965,021, size 1,638,130). Then range-GET only the selected deflated members (method 8; local header + compressed size) instead of the whole 3.13 GB zip. In Python: zlib.decompressobj(-15) inflates each member. The PNT layout is a 1024-byte big-endian header with sample count as >I at offset 2 (477,927 in the probed file), then n big-endian int16 force samples starting at offset 1024. Trailing padding follows, so take exactly n. Emit little-endian int16.
- Novelty kind: new_modality
- Measurement type: snow_penetration_force
- Instrument line: SLF SnowMicroPen penetrometer, device S36M (2015-2020), WFJ DailySMP protocol
- Archive collection: envidat
- Novelty evidence: novelty.py --url raw_data.zip --terms SnowMicroPen 'snow penetrometer' envidat: no matches in recipes, registry, ledger, downstream or downstream_registry. --type snow_penetration_force --archive envidat: 0 and 0. No vocabulary type covers micro-penetrometer force profiles, and no EnviDat source is in the corpus.
- Homogeneity: Restricted to one instrument, file prefix S36M (SMP serial 36, 2015-2020 generation; S36N SMP5, S36E, S37M, WFJD, JULI and WFJK files are excluded), one site (Weissfluhjoch study plot), one protocol (DailySMP), and the expert-chosen BestOfDay=1 profile per day. Unit and scale are the same throughout (raw force ADC counts, same header conversion).
- Risks: (1) Licence ambiguity: the EnviDat page says CC-BY-SA while an MIT file sits in data/. Both are permissive; cite both. (2) The 3.1 GB zip must be accessed by member range requests; download.sh must parse the central directory and verify CRC32 per member. (3) The S36M header conversion factor could differ between firmware updates; the builder should check the header factor is constant and drop or split any outliers. (4) The profile includes air above the snow surface (low near-constant counts about 60-75) before the surface; this is native, so keep the whole file. (5) The header field layout beyond the sample count should be cross-checked against snowmicropyn's PNT reader.
- Probe evidence: HEAD raw_data.zip: 200, content-length 3,134,603,173, accept-ranges bytes. Range-read the zip tail and central directory: 7,626 .PNT plus 7,626 .ini members, PNT median uncompressed 671,744 B (min 27,648, max 1,274,880). Range-fetched one member (raw_data/20240308/S36N2360.PNT, 628 KB compressed to 958,976 B), header text 'SMP5 developed by Michael Hohl, SLF Electronics'. Decoded 477,927 >h samples at offset 1024: 13,357 distinct values, min 58, max 16,781, smooth depth-continuous signal, top value only 1.1%. raw_data.csv (444 KB) lists 7,564 files; BestOfDay=1 counts: S36M 478, S36N 403, S36E 242, S37M 86.

Proposed by the autocollect scout on 2026-10-14 (transcript `.data/pipeline/logs/scout_16bit/scout.20261014_132438.jsonl`).
