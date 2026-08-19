# Rejected: Sandia SpecUtils gamma-spectrum fixtures as uint16

- **Dataset ID:** `sandia_specutils_gamma_spectra_u16`
- **Date attempted:** 2026-08-19
- **Status:** rejected
- **Intended source:** measured gamma-ray detector channel-count spectra bundled
  with `sandialabs/SpecUtils`
- **Pinned commit inspected:**
  `b2b20fd5d5923996fc4c9d914c5480c420a410f2`
- **Discovery log:**
  `.data/logs/sandia_specutils_gamma_spectra_u16/discover.latest.log`
- **Discovery evidence:**
  `.data/discovery/sandia_specutils_gamma_spectra_u16/`

## Intended value

A coherent collection of gamma-ray detector pulse-height histograms would add
a new 16-bit material. Dense ordered channel counts differ from both the
accepted NICER photon-event channel sequences and the MAGIC Cherenkov-event
feature table.

One complete detector spectrum would be a natural sample, losslessly decoded
from an N42 `ChannelData` or SPE `$DATA:` count array and written as
little-endian uint16 only when every exact source count fits that range.

## Discovery performed

The bounded GitHub-tree discovery resolved the repository commit, captured the
root license and twenty license/notice/readme files, inventoried all 351 blobs,
and found only two bounded spectrum candidates:

- `bindings/python/examples/passthrough.n42`; and
- `unit_tests/test_data/spectra/Mn56_DetX_Shielded.n42`.

The first discovery summary incorrectly treated the legacy N42
`Compression="CountedZeroes"` token stream as literal channel counts because
the parser initially recognized only the newer `compressionCode` spelling.
The Mn-56 document also contains an undeclared `DHS:` extension prefix, though
its standard N42 spectrum payload remains structurally separable. The staged
discovery parser was corrected to recognize both compression attributes,
losslessly expand counted-zero runs with bounds checks, and isolate only that
complete non-payload extension block.

Corrected local analysis of the already downloaded fixtures found:

- 1,064 portal-monitor spectra plus one Mn-56 laboratory spectrum;
- 1,065 unique count arrays;
- exactly 16,384 channels in every array;
- 17,448,960 exact values, or 34,897,920 decoded uint16 bytes;
- source counts from 0 through 5,621; and
- no width overflow or need for numerical conversion.

Most portal spectra contain only a few distinct values because they are sparse
short-integration Poisson histograms. That low cardinality is legitimate
measurement structure rather than degeneracy.

## Why this source is rejected

The apparent sample count does not provide independent source breadth. All
1,064 portal arrays are detector/time slices from one roughly 33-second
occupancy recorded on 2010-01-23. The only other source context is one shielded
Mn-56 laboratory spectrum. Splitting a single occupancy into many natural
spectrum records does not cure the repository rule against intrinsically thin,
single-event scopes.

The repository declares LGPL-2.1 for the software project, but neither measured
fixture provides a file-specific rights statement or clear measurement-data
provenance. The project README does not explicitly establish that the LGPL
grant covers these third-party-looking measured spectra. Under the corpus's
cautious training-rights policy, repository inclusion alone is insufficient.

The files are format examples and regression fixtures, not a coherent,
independently documented radiation-measurement dataset. No training recipe or
payload was accepted.

## Retry condition

Do not retry this SpecUtils fixture set as training material. Gamma spectra
remain a worthwhile new domain, but retry only with a separately published
collection containing multiple independent detector runs or sources, explicit
CC0/CC BY or comparably clear data rights, documented integer channel counts,
and enough complete spectra to satisfy both aggregate and median-sample floors.
