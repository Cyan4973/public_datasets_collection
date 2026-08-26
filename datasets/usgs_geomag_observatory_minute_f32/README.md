# USGS Geomagnetic Observatory Minute Float32 — Preflight

This candidate targets minute-resolution geomagnetic field measurements from
the official USGS Geomagnetism Program web service. It is intended to add a
new ground-magnetometer domain rather than another weather, seismic, or image
family.

The first step is deliberately bounded. It retrieves official USGS reuse-policy
pages and six hours of JSON data for a small set of observatories. The probe
checks that the current service exposes multiple nonconstant magnetic
components with minute-like cadence and records the exact response schema.

Run from the repository root:

```bash
bash datasets/usgs_geomag_observatory_minute_f32/discover.sh
```

Results are written under
`.data/discovery/usgs_geomag_observatory_minute_f32/`, and the durable log is
`.data/logs/usgs_geomag_observatory_minute_f32/discover.latest.log`.

The successful preflight found populated `variation` data at Boulder, College,
Fredericksburg, and Honolulu. The `adjusted` queries returned correctly shaped
but empty arrays for the selected interval. The full candidate therefore uses
the service's `variation` product and the universally populated X, Y, and Z
components; Honolulu's F component is excluded because it was empty.

Run the full local workflow with:

```bash
bash datasets/usgs_geomag_observatory_minute_f32/download.sh
bash datasets/usgs_geomag_observatory_minute_f32/build.sh
bash datasets/usgs_geomag_observatory_minute_f32/verify.sh
```

The downloader requests 48 bounded calendar-month JSON responses covering
2024. The build uses one complete observatory/component/year as each natural
sample. Decimal source values are rounded once to IEEE-754 float32 and written
in canonical little-endian order. Nulls and documented large missing sentinels
are removed independently per component; unrelated station metadata and
timestamps do not become primary samples.
