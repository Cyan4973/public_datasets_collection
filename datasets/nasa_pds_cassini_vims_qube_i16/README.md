# NASA PDS Cassini VIMS native-16-bit discovery

This candidate targets source-native 16-bit visual/infrared imaging-
spectrometer cubes from the official NASA PDS Cassini VIMS archive. One PDS3
QUBE core would become one natural three-dimensional sample.

Run the bounded range-first preflight:

    bash datasets/nasa_pds_cassini_vims_qube_i16/discover.sh

The preflight fetches NASA's science-information policy, official PDS
directory/index metadata, and a bounded 32 KiB range prefix from each
candidate QUBE. Because attached labels end near the core offset, a range
probe can overlap a small prefix of numeric data; the summary reports that
overlap explicitly. Discovery never retains those bytes as training samples.

A product qualifies only if its attached or detached PDS3 label proves:

- Cassini VIMS provenance;
- a three-axis QUBE with `CORE_ITEM_BYTES = 2`;
- integer core words with explicit MSB or LSB byte order;
- positive `SAMPLE`, `BAND`, and `LINE` dimensions;
- explicit suffix-item geometry and width whose full extent is consistent
  with the file size;
- a record pointer and core extent consistent with the official file size;
- a bounded individual and aggregate payload size.

If discovery succeeds, the next stage will choose a bounded, diverse set of
targets and geometries, pin the exact products, and write a downloader plus a
strict PDS3 QUBE decoder. It will retain only core detector words and skip
declared side/band/line suffix cells. Every emitted word will be canonical
little-endian; PDS labels, headers, and ancillary data will not enter the
samples.

The accepted plan contains 120 exact QUBEs from six mission-spanning archive
directories. Run:

    bash datasets/nasa_pds_cassini_vims_qube_i16/download.sh
    bash datasets/nasa_pds_cassini_vims_qube_i16/build.sh
    bash datasets/nasa_pds_cassini_vims_qube_i16/verify.sh

The source list pins every filename, byte size, and SHA-256. The build validates
the attached label again, copies only `SUN_INTEGER` core words while honoring
the declared suffix layout, and changes byte order from big to little endian.
