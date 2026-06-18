# 8-bit Variety Hunt Errors 2026-06-14

## Summary

| dataset_id | stage | status | cause |
|---|---|---|---|
| `google_fonts_ofl_ttf_u8` | download/build/verify | ok | local `fonts-main.zip` archive was reused and bounded font-file selection passed validation |
| `mutopia_midi_files_u8` | download validation | rejected | local `MutopiaProject-master.zip` archive contains zero `.mid`/`.midi` files |
| `natural_earth_vector_shp_u8` | download/build/verify | ok | 12 Natural Earth ZIPs downloaded; build and verify completed |

The Mutopia repository-archive candidate is rejected in this form because the
archive does not contain MIDI payloads. A different official Mutopia endpoint or
a different symbolic-music source would be needed.

## Measured Dataset

| dataset_id | samples | primary bytes | min / p10 / p25 / median / p75 / p90 / max sample bytes | same-size fraction |
|---|---:|---:|---|---:|
| `google_fonts_ofl_ttf_u8` | 122 | 33,876,096 | 19,596 / 42,563.6 / 105,248 / 205,386 / 277,120 / 425,795.6 / 5,772,308 | 0.008197 |
| `natural_earth_vector_shp_u8` | 12 | 96,390,016 | 25,104 / 47,898.8 / 2,063,354 / 6,986,842 / 10,233,802 / 20,350,555.6 / 23,766,908 | 0.083333 |

## Local Logs

- `.data/logs/google_fonts_ofl_ttf_u8/download.latest.log`
- `.data/logs/natural_earth_vector_shp_u8/download.latest.log`

The generated Mutopia `.data` failure artifacts were later removed after the
candidate was recorded as rejected in
`attempts/20260614_rejected_mutopia_midi_files_u8.md`.
