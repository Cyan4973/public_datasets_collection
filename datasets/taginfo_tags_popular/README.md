# Taginfo Tags Popular

Source URL:
- `https://taginfo.openstreetmap.org/api/4/tags/popular?page={page}&rp=500`

This recipe paginates Taginfo's popular OpenStreetMap tag statistics. The
primary payload is restricted to native usage-count columns:

- total element count
- total element fraction
- node count
- node fraction
- way count
- way fraction
- relation count
- relation fraction

`projects` and `in_wiki` are emitted as auxiliary operational fields. Text
lengths are intentionally not emitted.
