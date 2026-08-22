# UCI EMG Data for Gestures Int8

This staged recipe targets the raw eight-channel surface-electromyography
(sEMG) recordings in UCI dataset 481. The signals were recorded with a Myo
armband while 36 participants performed static hand gestures in two sessions.

Each complete source recording/channel is one natural sample. UCI stores the
Myo readings as decimal physical values on an exact `1e-5` lattice. A complete
archive scan found that multiplying all 33,903,256 channel values by `100000`
produces exact integers spanning `-128..127`, with no off-lattice or
out-of-range value. The recipe therefore inverts that storage scale and emits
the recovered signed codes as int8 bytes; it does not round or quantize.
Timestamps, gesture labels, participant directory codes, filenames, and
CSV/text framing are not sample bytes.

This adds a new physiological sensing process: electrical skeletal-muscle
activation waveforms with burst/rest morphology, distinct from EEG, ECG,
audio, motion capture, and existing activity-label sequences.

Run:

```bash
bash staging/uci_emg_gestures_i8/download.sh
bash staging/uci_emg_gestures_i8/build.sh
bash staging/uci_emg_gestures_i8/verify.sh
```

The official archive, API metadata, and license page are pinned by size and
SHA-256. The build reparses the archive, validates every decimal value, and the
verification stage compares every output byte with a fresh decode.
