# Blocked: Zenodo Flow-Cytometry FCS UInt16

- Date: 2026-08-05
- Candidate: `zenodo_flow_cytometry_fcs_u16`
- Intended domain: flow-cytometry per-event fluorescence and scatter measurements
- Intended representation: native FCS list-mode unsigned 16-bit integer parameters
- Intended natural sample: one complete event-by-parameter matrix per FCS file

## Discovery performed

A license-first bounded search queried the Zenodo records API for flow
cytometry, FACS, FCS-file, and mass-cytometry records. It required an explicit
CC0 or CC BY license, cytometry semantics in record metadata, and direct `.fcs`
payloads between 100 KiB and 1 GiB.

The final pass examined 188 records, of which 90 had an allowed license and 76
had matching semantics. It found 501 direct FCS files and classified 500 using
bounded FCS HEADER, TEXT, and DATA-prefix range requests. The probe validated
FCS framing and metadata rather than inferring width from the filename.

## Result

No native-16-bit FCS file qualified:

- 490 files across 16 records declared `$DATATYPE=F`, meaning IEEE floating-
  point event storage;
- nine files from the CC BY 4.0 MetaClean3.0 record declared integer storage,
  but every parameter used `$PnB=32`; and
- one `cells.fcs` imaging-mass-cytometry export had noncanonical TEXT metadata
  that the strict bounded parser could not resolve.

One additional direct file was observed beyond the 500-file safety cap. Given
the broad result—499 conclusively classified files, all 32-bit—expanding the
same nondeterministically ranked search is not justified. No complete FCS
payloads were downloaded and no samples were built.

This is blocked rather than permanently rejected because older cytometers can
produce `$DATATYPE=I` files with `$PnB=16`; the broad current Zenodo results
simply did not expose one. Retry only with an exact permissively licensed file
or record whose FCS metadata is already known to declare uniform 16-bit integer
parameters. Do not repeat the same broad search without such a lead.

## Width-correct successor lead

The nine integer files are a credible separate 32-bit candidate under a new ID,
such as `zenodo_metaclean_fcs_i32`. They all come from Zenodo record `10639508`,
*MetaClean3.0: Robust and accurate removal of low-quality event measurements in
cytometry*, which declares CC BY 4.0. Their source files total 55,520,786 bytes,
and every parameter inspected declares `$PnB=32`.

Do not silently repurpose this 16-bit attempt. A dedicated 32-bit preflight
must verify the exact record metadata and license, complete FCS event geometry,
parameter semantics and ranges, DATA-segment sizes, non-degeneracy, and whether
the `CleanPositiveControl` material is synthetic or otherwise free of participant
privacy concerns before promotion.

Ephemeral evidence:

- `.data/logs/zenodo_flow_cytometry_fcs_u16/discover.latest.log`
- `.data/discovery/zenodo_flow_cytometry_fcs_u16/summary.json`
- `.data/discovery/zenodo_flow_cytometry_fcs_u16/qualified.tsv`
- `.data/discovery/zenodo_flow_cytometry_fcs_u16/rejected.tsv`
- `.data/discovery/zenodo_flow_cytometry_fcs_u16/query_failures.tsv`
