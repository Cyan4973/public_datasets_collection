# OpenNeuro ds004584 Resting-State 64-Cap Scalp EEG Float32 Recordings

- Candidate id: `openneuro_ds004584_pd_rest_eeg_f32`
- Width: float32
- Quantity: Scalp EEG voltage (microvolts) as native little-endian float32 in EEGLAB .fdt files: 63-64 channels from one BrainVision 64-channel cap, 500 Hz, about 2-minute eyes-open rest, Pz reference.
- Source: https://s3.amazonaws.com/openneuro.org/ds004584/
- Resources: https://s3.amazonaws.com/openneuro.org?list-type=2&prefix=ds004584/sub-&max-keys=1000, https://s3.amazonaws.com/openneuro.org/ds004584/sub-001/eeg/sub-001_task-Rest_eeg.fdt, https://s3.amazonaws.com/openneuro.org/ds004584/sub-001/eeg/sub-001_task-Rest_channels.tsv, https://s3.amazonaws.com/openneuro.org/ds004584/sub-001/eeg/sub-001_task-Rest_eeg.json, https://s3.amazonaws.com/openneuro.org/ds004584/dataset_description.json
- License: CC0
- License evidence: https://s3.amazonaws.com/openneuro.org/ds004584/dataset_description.json
- License quote: "Name": "Rest eyes open", ... "License": "CC0", ... "DatasetDOI": "doi:10.18112/openneuro.ds004584.v1.0.0"
- Natural record: One complete subject resting-state recording: the whole *_task-Rest_eeg.fdt matrix (63 or 64 channels x about 60k-171k time points, channel-interleaved float32 as distributed). The median record is 18.36 MB (about 4.59M values).
- Estimated samples: 30
- Estimated primary values: 152,000,000
- Estimated download bytes: 612,000,000
- Estimated primary bytes: 608,000,000
- Decode path: Pure stdlib. The .fdt is headerless little-endian float32 in EEGLAB [nbchan x pnts] column-major order, i.e. multiplexed with the channel index fastest. Take nbchan from the rows of *_channels.tsv (63 or 64), cross-check it against EEGChannelCount in *_eeg.json and against file size divisible by 4*nbchan; pnts = size/(4*nbchan). No MATLAB .set parsing is needed. Emit one float32 LE sample per recording (source layout), rejecting NaN/Inf and sizes that don't divide evenly.
- Novelty kind: new_source
- Novelty evidence: novelty.py --url .../ds004584/ --terms ds004584 EEGLAB fdt 'resting EEG': no term matches anywhere. The term 'eeg' hits only the local 16-bit recipes eeg_physionet and chbmit_physionet and the downstream 16-bit families eeg_c3/eeg_c4/eeg_cz. There is no EEG family at 32-bit locally or downstream, and this is a different source (OpenNeuro EEGLAB float export, not PhysioNet EDF int16).
- Homogeneity: Single site (University of Iowa Narayanan lab), single BrainVision 64-channel cap, ground AFz, reference Pz, 500 Hz, same eyes-open rest task, same EEGLAB export, one unit (uV). 122 of 149 recordings have 63 channels and 27 have 64 (same cap and unit). The builder may restrict to 63-channel recordings for strictness. Values are genuinely floating-point with no ADC lattice, unlike ds004148, whose float32 values sit on a 0.1 uV int16 grid and was rejected for that reason.
- Risks: Clinical cohort (100 Parkinson's patients, 49 controls). The data are de-identified CC0, but samples must contain only the signal arrays (no participants.tsv demographics or clinical scores). The preprocessing history isn't documented (values look re-referenced/filtered), so it should be documented as distributed. Recording lengths vary (sub-001 is 282 s; most are 120-145 s). The total population of 3.02 GB exceeds the cap, so pin a deterministic subset (e.g. the first ~30 by subject id) with sizes and checksums.
- Probe evidence: An S3 listing found 1,043 keys and 149 .fdt files totalling 3,020,968,040 B (min 15,190,560, median 18,360,720, max 43,180,200). sub-001 sidecar: EEGChannelCount 63, SamplingFrequency 500, RecordingDuration 281.66, EEGReference Pz, ManufacturersModelName 'Brain Vision'. channels.tsv has 63 rows. sub-049/090/140 have 64 channels, and their sizes divide evenly. 16 KB range reads of sub-001 and sub-010: values from -200 to 160 uV; the 0.1 uV lattice fraction is 0.002; per-channel windows have 1,984-2,000 distinct values out of 1,984-2,000; a smallest-step lattice fits fewer than 3% of values. dataset_description.json reports License CC0.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_32bit/scout.20261005_174424.jsonl`).
