# USGS Geomagnetic Observatory Minute Float32 — 2026-08-25

## Outcome

Accepted `usgs_geomag_observatory_minute_f32`: calendar-year 2024 X, Y, and Z
ground-magnetic-field component timelines from four USGS observatories. The
family contains 12 natural station/component/year samples, 6,296,742 float32
values, and 25,186,968 primary bytes.

## Domain and sample shape

This adds continuous ground-magnetometer measurements, a distinct physical
process from the existing seismic, weather, oceanographic, astronomical-image,
and catalog families. Each sample is one observatory/component/calendar-year
timeline. Sample lengths range from 524,164 to 525,373 retained minute
observations, with a median of 524,702.

The selected observatories are:

- Boulder (`BOU`);
- College (`CMO`);
- Fredericksburg (`FRD`); and
- Honolulu (`HON`).

X, Y, and Z are used because all four stations populated them during the
preflight interval. Honolulu's F array was empty and is excluded rather than
creating inconsistent field coverage.

## Source acquisition

The official USGS Geomagnetism Web Services endpoint serves a `Timeseries`
JSON representation with a 60-second sampling period and `variation` product
type. Month-long requests often returned HTTP 404 despite valid shorter
queries. The downloader therefore recursively bisects only rejected intervals,
validates every successful response, retains every raw response, and assembles
the validated pieces into 48 station/month documents.

The realized acquisition contains 120 raw API responses totaling 193,698,710
bytes. Each raw response URL, interval, size, and SHA-256 is recorded inside
the monthly assembly and repeated in `download_inventory.json`. The noisy 404
messages in the download log are rejected span probes, not missing data; the
run completed with all 48 months validated.

## Rights

The downloader preserves and checks the official USGS copyrights-and-credits
page. It states that USGS-authored or produced data and information are
considered to be in the U.S. Public Domain. The recipe retains USGS and
observatory attribution and contains no personal or participant data.

## Representation

The API publishes decimal JSON measurements and declares a digital sampling
rate of 0.01 nT. Each retained finite value below the 99999-class missing range
is rounded once to IEEE-754 binary32 and written in canonical little-endian
order. This is declared `derived_operational_numeric`: float32 resolution over
the observed range remains finer than the source's declared 0.01-nT digital
sampling resolution.

Across the 12 samples, 27,738 of 6,324,480 expected minute slots were null or
missing, leaving 99.56% coverage. Missing observations are omitted independently
per component and do not create numeric sentinels.

## Validation notes

Build and independent source-to-output verification passed. Verification
reparses all 48 monthly assemblies and their raw-chunk inventories, recomputes
every output byte from the local JSON values, checks little-endian float32
encoding, hashes, coverage, natural boundaries, non-degeneracy, and aggregate
acceptance limits.

Boulder contains a source-provided near-zero interval from 2024-07-03 through
2024-07-08. Inspection confirmed the same `NT/R0` X/Y/Z channel identities
before and during that interval, so the values are retained as instrument
behavior rather than treated as an assembly or missing-value error.
