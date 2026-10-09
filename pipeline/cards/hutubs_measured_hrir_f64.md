# HUTUBS (TU Berlin) Measured Head-Related Impulse Responses, 96 Subjects, 440 Directions, SOFA Data.IR Float64

- Candidate id: `hutubs_measured_hrir_f64`
- Width: float64
- Quantity: Measured binaural head-related impulse responses: the free-field acoustic transfer from 440 loudspeaker directions to both blocked ear canals of human subjects. 256 taps at 44.1 kHz. Signals are deconvolved and processed, stored natively as double in SOFA (netCDF4/HDF5) Data.IR, shape [M=440, R=2, N=256].
- Source: https://depositonce.tu-berlin.de/items/dc2a3076-a291-417e-97f0-7697e332c960
- Resources: https://sofacoustics.org/data/database/hutubs/, https://sofacoustics.org/data/database/hutubs/pp1_HRIRs_measured.sofa, https://sofacoustics.org/data/database/hutubs/Documentation.pdf
- License: CC BY 4.0
- License evidence: https://depositonce.tu-berlin.de/items/dc2a3076-a291-417e-97f0-7697e332c960
- License quote: DepositOnce item page: 'Creative Commons Attribution (CC BY)' linked to CC BY 4.0. Each SOFA file also carries the global attribute License = 'cc-by 4.0 (https://creativecommons.org/licenses/by/4.0/)' (read from the pp1_HRIRs_measured.sofa header), so the grant covers the exact objects.
- Natural record: One subject's measured HRIR SOFA file, ppN_HRIRs_measured.sofa: 440 directions x 2 ears x 256 taps = 225,280 float64 values (about 1.8 MB).
- Estimated samples: 96
- Estimated primary values: 21,600,000
- Estimated download bytes: 160,000,000
- Estimated primary bytes: 173,000,000
- Decode path: The sofacoustics.org Apache listing has 192 .sofa files: ppN_HRIRs_measured.sofa about 1.66 MB and ppN_HRIRs_simulated.sofa about 5.8 MB. download.sh fetches only the 96 measured files with curl and pins sizes and sha256. As a check against the canonical archive, it greps each file's SOFA License attribute and DatabaseName=HUTUBS. A pure-stdlib HDF5/netCDF4 reader locates the Data.IR variable, reads its datatype (expected IEEE f64 LE) and layout (contiguous or chunked plus deflate via zlib), and emits the [440,2,256] array as little-endian float64, one sample per subject.
- Novelty kind: new_modality
- Measurement type: head_related_impulse_response
- Instrument line: tu_berlin_anechoic_hrtf_rig
- Archive collection: sofacoustics.org/hutubs
- Novelty evidence: `novelty.py --url https://sofacoustics.org/data/database/hutubs/ --terms HUTUBS HRTF HRIR sofa`: no matches in recipes, registry, ledger or downstream. `--type room_impulse_response`: only openslr_rirs_noises_pcm16 (16-bit) and aalto_arni_room_impulse_response_f32 (32-bit). No impulse-response family exists at 64-bit, and the sofacoustics archive is unused. HRIRs are short (256-tap) anechoic, direction-dependent ear responses with pinna notches, unlike long reverberant room responses.
- Homogeneity: One measurement program: the same TU Berlin anechoic-chamber rig, 440-direction sampling grid, 44.1 kHz, 256 taps and processing chain for every subject, with one quantity (impulse-response amplitude). The simulated BEM HRIRs (1730 directions, a different generation process) are excluded; if wanted, they would be a separate family.
- Risks: (1) Data.IR's float64 storage is inferred, not yet parsed. The file is 1.66 MB against 1.80 MB of raw doubles, which fits light deflate on f64; f32 would be only 0.9 MB. The builder must confirm the HDF5 datatype message. (2) The sofacoustics mirror stands in for the DepositOnce HRIRs.zip (1.27 GB, which also holds simulated data); the per-file License attribute shows the mirror carries the same CC BY 4.0 grant. (3) 96 samples of fixed shape could look like a 'near-duplicate fixed-length series'. However each is a different person's anatomy, and responses vary strongly across 880 direction/ear channels. (4) Two HUTUBS subjects are FABIAN dummy-head repeats per the documentation, which is acceptable and documented.
- Probe evidence: The directory listing is live (HTTP 200) with 192 .sofa entries. HEAD on pp1_HRIRs_measured.sofa returned Content-Length 1,659,720. A 64 KB range GET showed the HDF5/netCDF header with attributes DataType=FIR, License='cc-by 4.0 (https://creativecommons.org/licenses/by/4.0/)', Organization='Audio Communication Group, Technical University Berlin; HUAWEI ...', Title='head-related impulse responses', DatabaseName=HUTUBS, ListenerShortName=pp1, and variables Data.IR, Data.SamplingRate, Data.Delay. A WebFetch of the DepositOnce item confirmed CC BY 4.0 and the files Documentation.pdf, HRIRs.zip (1.27 GB), HpIRs.zip and 3D head meshes.zip.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_015508.jsonl`).
