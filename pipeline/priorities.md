# Autocollect user priorities

Read by the driver into every scout prompt.

## Point clouds, notably from LAZ (2026-10-08)

The user is especially interested in point-cloud data extracted from `.laz`
files. `tools/laz/laszip.py` decodes LAZ in pure Python (LAS 1.0-1.4, point
formats 0-3 and 6-8; about 60,000 points/s), so LAZ is no longer a tooling
blocker. Typical sources: national and regional lidar programs (USGS 3DEP,
including the public AWS bucket; AHN Netherlands; Denmark; Finland NLS; Spain
PNOA; UK Environment Agency; Swisstopo), OpenTopography, NOAA Digital Coast,
and mobile, terrestrial or photogrammetric scan collections with explicit
licenses.

A LAS point record spans every width:
- 8-bit: classification, return number and count, scan angle, user data
- 16-bit: intensity, RGB, NIR, point source id
- 32-bit: X, Y, Z as scaled int32 record coordinates (absent from the corpus)
- 64-bit: GPS time

Keep families homogeneous: one field from one program or sensor regime per
family, one sample per tile or file (natural boundary, bounded subset of
tiles). Fields that look like the existing DC LiDAR 2015 families (intensity
u16, classification u8, GPS time f64) may be rejected by the byte gate;
integer coordinates, RGB/NIR and multi-return structure from other sensors
are the most likely to be new.
