# Blocked: Zenodo COMTRADE Power-Grid Waveforms Int16

- Date: 2026-08-02
- Candidate: `zenodo_comtrade_i16`
- Intended domain: power-grid fault and relay oscillography
- Intended width: native signed-int16 analog channels in IEEE COMTRADE

## Attempt

A license-first Zenodo metadata search used six power-system/COMTRADE queries,
admitted only explicit CC0 or CC BY records, and looked for either direct
same-basename `.cfg`/`.dat` pairs or such pairs inside ZIP central
directories. Direct pairs were to be qualified only when the configuration
declared `BINARY` COMTRADE data and the bounded data prefix matched its int16
record layout.

## Result

- unique records searched: `107`
- records rejected for license: `13`
- direct `.cfg`/`.dat` pairs: `0`
- permissively licensed ZIP archives examined: `16`
- ZIP archives containing bounded matching pairs: `0`

The archive hits were unrelated uses of “Comtrade” (notably international
trade data) or unrelated software/microscopy archives. One unrelated archive
had a central directory larger than the bounded tail, but its record metadata
did not describe electrical COMTRADE observations.

No dataset payload was downloaded.

## Status and retry condition

This route is blocked, not a rejection of the COMTRADE domain. Retry only with
an exact source page or archive URL whose terms explicitly permit training and
redistribution and whose inventory is known to contain IEEE COMTRADE
`.cfg`/`.dat` pairs. Do not repeat the broad Zenodo keyword search.

Evidence:

- `.data/logs/zenodo_comtrade_i16/discover.latest.log`
- `.data/discovery/zenodo_comtrade_i16/summary.json`
- `.data/discovery/zenodo_comtrade_i16/candidates.tsv`
- `.data/discovery/zenodo_comtrade_i16/archives.tsv`
