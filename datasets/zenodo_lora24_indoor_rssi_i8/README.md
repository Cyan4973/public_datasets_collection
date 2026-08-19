# Indoor LoRa 2.4 GHz RSSI Timelines Int8

Exact-source recipe for
[Zenodo record 7106074](https://zenodo.org/records/7106074), *Dataset: Indoor
Performance Evaluation of LoRa 2.4GHz*.

The CC BY 4.0 record documents two controlled experiments between three fixed
end nodes and one gateway in an INRIA office building:

- an exhaustive configuration sweep where each node sent 50 packets for every
  LoRa 2.4 GHz configuration; and
- a week-long run where the nodes repeatedly used six configurations.

The two CSVs total 25,423,999 bytes. Bounded discovery already established
exact integral RSSI values within signed-int8 range. This preflight resolves
the natural grouping keys and node encoding before any complete acquisition.

It downloads only the record metadata, 228-byte readme, two published plotting
scripts totaling about 35 KB, and 1 MiB head/tail ranges of each CSV. It checks
the pinned small-file MD5 values, profiles all columns and configuration keys,
and writes evidence under
`.data/discovery/zenodo_lora24_indoor_rssi_i8/`.

Run:

```bash
bash datasets/zenodo_lora24_indoor_rssi_i8/preflight.sh
```

No complete experiment CSV is downloaded by this step.

The preflight confirmed the official node decoder and radio-configuration
structure. To acquire and build the complete candidate:

```bash
bash datasets/zenodo_lora24_indoor_rssi_i8/download.sh
bash datasets/zenodo_lora24_indoor_rssi_i8/build.sh
bash datasets/zenodo_lora24_indoor_rssi_i8/verify.sh
```

The exhaustive sweep emits one complete RSSI timeline per fixed node. The
week-long experiment emits one timeline per fixed node and radio configuration.
Only valid 20-byte node packets recognized by the source's published decoder
are retained.

The complete build verified 21 nonconstant samples and 215,232 signed-int8
values. Sample lengths range from 5,192 to 21,446 packets, with a median of
8,732. All three exhaustive node sweeps and all 18 week-long node/configuration
groups qualify.
