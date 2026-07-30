# NOAA IMS daily snow and ice cover (u8)

Accepted recipe for complete 4 km Northern Hemisphere snow/ice category grids
from the NOAA/U.S. National Ice Center Interactive Multisensor Snow and Ice
Mapping System (IMS), distributed by NSIDC as product G02156.

The default selection pins the first day of every month in leap year 2024.
Each source file is one natural daily analysis record with a 6,144 by 6,144
grid. The build removes the documented 30-line ASCII header and writes the
source category codes 0 through 4 unchanged as `uint8`. It does not preserve
gzip/container bytes, crop grids, combine days, resample, or remap classes.

The expected primary output is 12 samples and 452,984,832 bytes. The compressed
download should be much smaller.

## License

IMS is an official U.S. Government NOAA/USNIC product and is treated as U.S.
Government public-domain data. Retain the upstream citation, DOI
`10.7265/N52R3PMC`, NOAA/USNIC/NSIDC attribution, product version, and analysis
dates. This is permissive for training use; attribution and provenance remain
required by this recipe.

## Run

From the repository root:

```bash
bash datasets/noaa_ims_snow_ice_cover_u8/download.sh
```

The pinned `_00UTC_` filenames were confirmed from the official 2024 archive
listing. The script fails visibly on HTTP errors, invalid gzip payloads, or
implausible decompressed sizes. If NSIDC moves the same exact year directory,
rerun with:

```bash
IMS_BASE_URL='https://official-mirror.example/NOAA/G02156/4km/2024' \
  bash datasets/noaa_ims_snow_ice_cover_u8/download.sh
```

After a successful download, the local-only acceptance steps are:

```bash
bash datasets/noaa_ims_snow_ice_cover_u8/build.sh
bash datasets/noaa_ims_snow_ice_cover_u8/verify.sh
```
