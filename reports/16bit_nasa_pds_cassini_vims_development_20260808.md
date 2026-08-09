# NASA PDS Cassini VIMS int16 development — 2026-08-08

## Outcome

Accepted `nasa_pds_cassini_vims_qube_i16`: 120 source-native signed-int16
spectral QUBE cores from the Cassini Visual and Infrared Mapping Spectrometer.

## Domain value

This adds spacecraft planetary imaging spectroscopy. The existing Venere
hyperspectral source is one terrestrial laboratory scan of a painting
reconstruction; VIMS contributes time-separated spacecraft observations of
Saturn, Titan, small moons, the Sun, and sky calibration fields, with ten
natural spatial geometries and a fixed 352-band spectral axis.

## Discovery and selection

Bounded discovery began from the official PDS Imaging Cassini archive and
validated NASA SMD policy language, 94 available COVIMS volumes, official
directory/index metadata, and attached PDS3 labels. Eight evenly spaced
volumes were examined to avoid bias toward the cruise/Jupiter-era beginning of
the archive listing. The final plan retains all 120 unique qualifying QUBEs
encountered before the fixed discovery bound, drawn from six product-bearing
directories in volumes 0001, 0014, 0028, 0041, 0054, and 0067.

An early discovery implementation requested fixed 512 KiB file prefixes.
Because attached labels ended at offsets near 24 KiB, the successful run
fetched 52,167,680 range bytes, of which 49,328,128 overlapped core prefixes.
Those ephemeral probe bytes were never used as samples. The tracked discovery
script now limits future probes to 32 KiB and reports any numeric overlap
explicitly. Full acquisition remained a separate user-run, hash-pinned step.

## Accepted material

- 120 natural three-dimensional QUBE core samples
- 89,698,752 signed-int16 values and 179,397,504 primary bytes
- source QUBEs total 194,715,648 bytes
- all cubes have 352 spectral bands
- ten spatial geometries, from `64 x 1` through `64 x 64`
- targets: Saturn 39, Titan 38, sky 32, Sun 8, Atlas 1, Bestla 1, unknown 1
- stored range: -32,501 through 32,353
- 10,747,156 negative words and 8,291,468 zero words
- 65,911,832 adjacent-value transitions
- 60 through 4,334 distinct values per cube; median 1,157

Every selected source passed nondegeneracy and output-uniqueness checks.

## PDS layout and conversion

The attached labels identify Cassini/VIMS and declare three QUBE axes in
`SAMPLE, BAND, LINE` order, two-byte `SUN_INTEGER` core words, dimensionless
`RAW_DATA_NUMBER` values, and identity base/multiplier scaling. Source cubes
use PDS suffix layouts `(1,2,0)` or `(1,4,0)` with explicitly
declared suffix widths.

The decoder traverses the expanded PDS layout, copies only core cells, skips
all sample/band/line suffix cells, and reverses each big-endian core word to
canonical little-endian signed int16. It performs no arithmetic calibration,
resampling, cropping, splitting, or concatenation. Independent verification
reparses and re-extracts all sources and byte-compares every emitted cube.

## License and safety

These are public Cassini mission observations served by the official NASA PDS
Imaging archive. NASA SMD states that SMD-funded scientific information is
held as a public trust, made publicly available, and openly shared. Mission,
instrument, dataset, and product attribution are retained. The samples contain
only robotic planetary/calibration detector values and no personal or
sensitive information.
