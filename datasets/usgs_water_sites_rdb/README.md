USGS water site registry numeric fields extracted from public NWIS RDB
stream-site exports.

The downloader fetches deterministic state-level inventories under
`.data/downloads/usgs_water_sites_rdb/site_inventory/`. The builder keeps only
complete rows for the six numeric site fields so every emitted series has the
same site axis:

- USGS site number (auxiliary identifier)
- decimal latitude
- decimal longitude
- altitude
- altitude accuracy
- hydrologic unit code

The default repair bar is 20,000 complete site records, producing 100,000
primary numeric values across the five primary homogeneous series. The site
number is emitted only as auxiliary alignment metadata and does not count toward
acceptance.
