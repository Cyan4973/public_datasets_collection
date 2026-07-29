# OpenStreetMap daily way-node references — int64

This draft decodes ordered `<nd ref="…">` graph-topology references from
versioned OpenStreetMap daily replication diffs. It emits one signed int64
sample per immutable daily `.osc.gz` diff, preserving XML/way/reference order.

The primary values are actual node references used by edited ways—not hashes,
object payload bytes, XML bytes, or compressed data. References are required to
exceed the 32-bit unsigned range, proving that 64-bit storage is meaningful.

License: Open Database License 1.0. Preserve OpenStreetMap contributor
attribution.

## Run

```bash
bash datasets/osm_daily_way_references_i64/download.sh
bash datasets/osm_daily_way_references_i64/build.sh
bash datasets/osm_daily_way_references_i64/verify.sh
```

The accepted candidate pins immutable daily replication sequences `5066`,
`5067`, and `5068`, covering 2026-07-27 through 2026-07-29 UTC. The downloader
validates exact source sizes and SHA-256 hashes before semantic XML inspection.
