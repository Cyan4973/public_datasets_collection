`nyc_311_descriptor_u16` emits a pinned `uint16` descriptor-ID stream from NYC 311 service requests.

Scope:
- public NYC 311 dataset
- fixed January 2024 slice
- one operational categorical field: `descriptor`
- preserve CSV row order from the downloaded export

Transform:
- keep rows in source order
- map distinct non-empty descriptor strings to stable lexicographic `uint16` ids
- reserve code `0` for missing descriptors
- emit deterministic contiguous shards

Files:
- `download.sh` fetches a bounded public CSV slice into `.data/downloads/`
- `build.sh` constructs the pinned dictionary and emits raw `uint16` samples
- `verify.sh` checks input presence, sample sizes, and `samples.jsonl`
