# PolarFront EK60 power int16 development — 2026-08-04

## Outcome

Accepted `zenodo_polarfront_ek60_power_i16`, native signed-int16 water-column
acoustic power profiles from Zenodo record `7473204`, *Split-beam echosounder
data from keel-mounted EK60 during PolarFront 2022-05 cruise*, DOI
`10.5281/zenodo.7473204`, released under CC0.

## Domain distinction

The existing ADCP family stores Doppler-derived water velocity components.
This family stores raw active acoustic echo-power words across range bins,
capturing water-column, biological, and seabed backscatter. Earlier USGS
sidescan searches produced no accepted samples; this is the corpus's first
accepted sonar-backscatter family.

## Source and decoding

The exact 45,896,704-byte source is pinned by MD5
`944f3af1aea3a51cfa7ef7912dde10ba`. A strict decoder validates all 33,849
length-framed Simrad datagrams:

- 1 `CON0` configuration identifying PolarFront0522, ER60, and 18/38/120 kHz
  transducers;
- 30,407 `NME0` navigation datagrams, validated but excluded; and
- 3,441 `RAW0` mode-3 datagrams.

Every one of 1,147 strictly ordered ping timestamps contains channels 1, 2,
and 3 exactly once at 18, 38, and 120 kHz. Each RAW0 holds 3,188 signed-int16
power words plus separate int8 angle pairs. Only the typed power field is
emitted, byte-exactly and in source order.

## Accepted material

- 3,441 complete ping/channel range profiles
- 3,188 values and 6,376 bytes per sample
- 10,969,908 values and 21,939,816 numeric bytes total
- 3,441 unique payload hashes
- global raw range -18,746 through 2,404
- at least 1,431 distinct power codes per profile
- no zero values
- zlib-9 ratios approximately 0.801 through 0.870, median about 0.846

## License and safety

The Zenodo record declares CC0. Samples contain only instrument power words;
navigation text, ship position, and all container/configuration bytes are
excluded. No personal or sensitive data is present.
