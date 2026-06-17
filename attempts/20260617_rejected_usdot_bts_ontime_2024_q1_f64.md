# Rejected: usdot_bts_ontime_2024_q1_f64

Date: 2026-06-17

Candidate material: U.S. DOT BTS TranStats on-time flight performance records
for 2024 Q1, intended as float64 columns for departure delay, arrival delay,
air time, taxi-out, taxi-in, and distance.

Reason rejected: the recipe was based on guessed TranStats PREZIP archive
filenames. The first Reporting Carrier filename family returned HTTP 404 for
January, February, and March 2024. A retry using the likely Marketing Carrier
filename family, with the Reporting Carrier family as fallback, also returned
HTTP 404 for all three selected months.

Outcome: no payloads were downloaded, no build was possible, and the ignored
`staging/usdot_bts_ontime_2024_q1_f64/` recipe was removed to avoid future
agents misclassifying it as merely unfinished.

Do not retry this candidate without exact verified archive URLs or a different
official BTS extraction path.

Related report: `reports/64bit_hunt_20260617_failures.md`.
