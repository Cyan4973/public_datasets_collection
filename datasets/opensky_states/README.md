# OpenSky State Vectors

Pinned OpenSky states snapshot with aircraft position and motion values.

Pinned source: `https://opensky-network.org/api/states/all`

Selected series:
- `opensky_longitude`
- `opensky_latitude`
- `opensky_geo_altitude_m`
- `opensky_velocity_mps`
- `opensky_heading_deg`

Missing-value policy: Filters out state vectors with null longitude, latitude, altitude, velocity, or heading.
