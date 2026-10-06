# NHANES 2005-2006 Physical Activity Monitor (ActiGraph AM-7164) Minute-by-Minute Device Intensity Counts UInt16

- Candidate id: `nhanes_paxraw_d_actigraph_intensity_u16`
- Width: uint16
- Quantity: Hip-worn ActiGraph AM-7164 uniaxial accelerometer device intensity value (activity counts per minute, documented range 0-32767), 7 consecutive days of free-living wear per participant
- Source: https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2005/DataFiles/PAXRAW_D.htm
- Resources: https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2005/DataFiles/PAXRAW_D.ZIP
- License: US Government public domain (NCHS/CDC)
- License evidence: https://wwwn.cdc.gov/nchs/NHANES/NhanesCitation.aspx
- License quote: Generally, data and materials produced by Federal agencies are in the public domain and may be reproduced without permission.
- Natural record: One participant's (SEQN) complete PAXINTEN minute series in PAXN order: up to 10,080 values (7 days x 1,440 min).
- Estimated samples: 7,400
- Estimated primary values: 74,874,095
- Estimated download bytes: 470,990,068
- Estimated primary bytes: 149,748,190
- Decode path: curl the single 470,990,068-byte ZIP. It holds one deflate member, paxraw_d.xpt (2,994,965,840 bytes uncompressed), so there is no need to extract to disk: stream it with zipfile/zlib. Parse SAS XPORT v5: 80-byte header records, a NAMESTR block of 9 x 140-byte entries, then fixed 40-byte rows. Variables SEQN(5) PAXSTAT(4) PAXCAL(4) PAXDAY(4) PAXN(5) PAXHOUR(4) PAXMINUT(4) PAXINTEN(5) PAXSTEP(5) are big-endian truncated IBM/360 floats. Decode them with a 10-line stdlib function, group by SEQN, order by PAXN, and emit PAXINTEN as uint16 LE. SEQN and the flags are auxiliary or filters only.
- Novelty kind: new_source
- Novelty evidence: novelty.py on the PAXRAW_D URL found no URL matches and no term hits for actigraph, nhanes, 'physical activity', 'activity counts', or PAXINTEN in any layer. There is no NCHS/NHANES recipe in datasets/ or attempts/ (only two unrelated CDC COVID transient failures). Wearable actigraphy is absent locally and downstream (downstream har_* is UCI HAR float, and honeybee_accelerometer_pcm16 is insect vibration).
- Homogeneity: One device model (ActiGraph AM-7164), one protocol (7-day hip wear, 1-minute epochs), one quantity (device counts). The codebook says PAXINTEN hard edits are 0 to 32767, with 74,874,095 values and 0 missing. Optionally restrict to participants with PAXSTAT=1 (reliable) and PAXCAL=1 (in calibration). That is a documented quality filter, not a regime split. Use the 2005-06 cycle only. PAXRAW_C (2003-04, 427.5 MB, same device, 8 variables, 35-byte rows) is a same-regime extension if more volume is wanted.
- Risks: NCHS public-use files carry a statistical-use and no-re-identification notice alongside the public-domain statement. The judge may weigh it, but no identifiers are emitted (SEQN is dropped). Extraction ratio is ~1/3 of the compressed download and the XPT is 3 GB uncompressed, so stream-decode rather than extract to stay under the per-candidate byte cap. Many zero counts (sleep, non-wear) make the material low-entropy but genuine. The CDC host is slow-ish: use resumable curl -C -. Some participants have fewer than 10,080 rows; keep the natural length.
- Probe evidence: HEAD returned HTTP 200, application/x-zip-compressed, content-length 470,990,068, last-modified 2014-12-31. The central directory (last 64 KB) shows 1 entry, paxraw_d.xpt, method 8, csize 470,989,910, usize 2,994,965,840. The first 256 KB range was inflated (1.57 MB): XPT LIBRARY/MEMBER/NAMESTR headers with 9 variables and a 40-byte row length. The first 3,000 rows decoded: SEQN 31128, PAXN 1..3000, integer PAXINTEN 0..4873 with 752 distinct values. The PAXRAW_D.htm codebook confirms the ActiGraph AM-7164 and the 0-32767 range.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_16bit/scout.20261005_215706.jsonl`).
