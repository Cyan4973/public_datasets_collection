# Open Ephys Mouse Extracellular Voltage Int16

This recipe extracts four synchronized native big-endian signed-int16 neural
voltage streams from a CC BY 4.0 mouse Open Ephys recording.

Run:

```bash
bash datasets/zenodo_open_ephys_continuous_i16/download.sh
bash datasets/zenodo_open_ephys_continuous_i16/inspect.sh
bash datasets/zenodo_open_ephys_continuous_i16/build.sh
bash datasets/zenodo_open_ephys_continuous_i16/verify.sh
```

The selected electrode channels are CH1, CH6, CH11, and CH16. Each output is
one complete 66,593,792-sample stream. The decoder validates all legacy Open
Ephys timestamps, sample counts, and record markers, then removes only framing
and concatenates the source-order big-endian int16 sample words.
