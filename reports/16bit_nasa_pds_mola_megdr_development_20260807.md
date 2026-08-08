# NASA PDS MOLA MEGDR int16 development — 2026-08-07

## Outcome

Accepted `nasa_pds_mola_megdr_i16`: four complete native signed-int16
Mission Experiment Gridded Data Record topography quadrants from the Mars
Global Surveyor Mars Orbiter Laser Altimeter.

## Domain value and overlap

This is planetary laser-altimeter terrain rather than another terrestrial
sensor stream. The corpus already has one Earth SRTM HGT elevation tile, but
MOLA adds a different planet, instrument, acquisition geometry, interpolation
pattern, global extent, and much larger natural raster shape. It also differs
from accepted Mars THEMIS imagery and SHARAD radargrams in both physical
quantity and numeric representation.

## Source and selection

Discovery traversed the official NASA PDS Geosciences hierarchy and inspected
92 PDS3 labels without downloading image payloads. It found 39 native
big-endian signed-int16 products, of which 11 were topography. The accepted
subset is the complete four-product 64-pixels/degree global partition:

- `MEGT00N000GB`: south, 0–180 degrees east
- `MEGT00N180GB`: south, 180–360 degrees east
- `MEGT90N000GB`: north, 0–180 degrees east
- `MEGT90N180GB`: north, 180–360 degrees east

Lower-resolution duplicate maps and the areoid, observation-count, and radius
product families are excluded. The higher-resolution 128-pixels/degree family
would require a substantially larger tiled collection and adds resolution
rather than a new numeric domain.

## Accepted material

- 4 natural two-dimensional quadrant samples
- shape `5760 x 11520` per sample
- 66,355,200 signed-int16 values and 132,710,400 bytes per sample
- 265,420,800 values and 530,841,600 primary bytes total
- PDS-declared unit: meter
- observed global stored range: -8,199 through 21,218
- simple cylindrical, planetocentric, east-positive map coordinates
- 0.015625 degree (64 pixels/degree), approximately 0.926 km/pixel

The label defines topography as planetary radius minus the GMM3 areoid radius.
Each cell is the median observed topography in its bin; PDS supplies an
interpolated value where no observation lies in a cell, so there is no native
missing-value sentinel to remove.

## Identity and conversion

Source IMG SHA-256 values, in product order above:

- `59313efe92045324503e54f130ddc29096668523ae8dd0e6d64553cc8144c193`
- `6cec4b2a319dc3f1d699a73cef303e097bcd9cd490ff85c412c725e1d81ae4a3`
- `95b492b0670e0f572736820c13c3907a5294a04aa21cbbddd30e038bbd46f1b6`
- `72c9ea46b2e2485718cddfc0041fec76d9024020d93d6ddf985ac727988d7e9a`

Every PDS label declares `SAMPLE_TYPE=MSB_INTEGER`, `SAMPLE_BITS=16`, and
`UNIT=METER`. The build only byte-swaps words to the repository's canonical
little-endian representation. It does not resample, crop, split, concatenate,
or numerically transform any grid.

## License and safety

The source is NASA PDS public scientific mission data produced by the MGS MOLA
Team at Goddard Space Flight Center. This uses the same NASA PDS public-data
classification already established for accepted SHARAD and THEMIS recipes;
mission, instrument, data-set ID, and PDS attribution are retained. The grids
describe Mars and contain no personal or sensitive information.
