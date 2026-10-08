# DFL Bundesliga Official Optical Position Tracking (Bassek et al. 2025, 7 matches) 25 Hz Player/Referee Pitch Coordinates and Speed, Float32

- Candidate id: `figshare_dfl_bundesliga_position_tracking_f32`
- Width: float32
- Quantity: Player and referee pitch-plane position X and Y (metres, pitch-centred, 0.01 m resolution) and speed S (m/s) at 25 Hz from the DFL official camera tracking system
- Source: https://springernature.figshare.com/articles/dataset/An_integrated_dataset_of_spatiotemporal_and_event_data_in_elite_soccer/28196177
- Resources: https://ndownloader.figshare.com/files/51643514, https://ndownloader.figshare.com/files/51643517, https://ndownloader.figshare.com/files/51643520, https://ndownloader.figshare.com/files/51643523, https://ndownloader.figshare.com/files/51643526, https://ndownloader.figshare.com/files/51643529, https://ndownloader.figshare.com/files/51643532, https://api.figshare.com/v2/articles/28196177
- License: CC-BY-4.0
- License evidence: https://api.figshare.com/v2/articles/28196177
- License quote: figshare article 28196177 license: {'value': 52, 'name': 'CC BY', 'url': 'https://creativecommons.org/licenses/by/4.0/'}; description: 'This dataset contains seven matches of official match data from the German Bundesliga first and second division ... the first dataset of official position data from an elite soccer competition.'
- Natural record: One <FrameSet> = one person (player or referee) for one GameSection (half) of one match: ~65,000-75,000 consecutive 25 Hz frames each carrying X, Y, S. ~7 matches x 2 halves x ~25 persons ≈ 350 framesets.
- Estimated samples: 350
- Estimated primary values: 70,000,000
- Estimated download bytes: 2,622,600,000
- Estimated primary bytes: 280,000,000
- Decode path: curl the seven DFL_04_03_positions_raw_observed_*.xml files (349-419 MB each, sizes pinned from the figshare API); stream-parse with xml.etree.ElementTree.iterparse (or line regex, each <Frame .../> is one line); per FrameSet emit float(X), float(Y), float(S) as struct '<f' into three series; ball FrameSet (TeamId 'BALL', has Z/BallStatus) excluded or kept as its own series, not mixed with persons.
- Novelty kind: new_source
- Measurement type: sports_player_tracking
- Instrument line: dfl_optical_tracking_25hz
- Archive collection: springernature.figshare.com/28196177
- Novelty evidence: novelty.py --url <figshare article> --terms bundesliga 'position data' soccer: no matches in recipes, registry, ledger, downstream, downstream_registry. Existing sports material is statsbomb event pitch locations (sparse event coordinates) and chess.com games; existing trajectory_positions families are AIS/ADS-B/vehicle/vessel GNSS tracks. No optical sports player-tracking family exists locally or downstream.
- Homogeneity: One provider (DFL/ChyronHego-style optical tracking), one coordinate frame (pitch-centred metres, 105x68 pitch), one 25 Hz lattice, 2-decimal quantization for all persons; X, Y and S are separate series. Ball frames (different dynamics, extra Z) kept out of the person series.
- Risks: Full download ~2.6 GB XML (could be narrowed to 3-4 matches if the byte cap requires; framesets per match are complete natural records). X/Y are 2-decimal smooth trajectories and may sit near walking marker trajectories or AIS in byte statistics — S (speed) and the pitch-bounded range should help. Data are about identifiable professional athletes (public match performance, published CC BY in Scientific Data); ids are DFL-OBJ codes, no names needed in output.
- Probe evidence: figshare API: CC BY license, 21 files incl. 7 positions_raw_observed XMLs sized 348,945,715-418,524,833 B. Range GET 0-3000 of file 51643514: <PitchSize X="105.00" Y="68.00"/>, <FrameSet GameSection="firstHalf" ... TeamId="referee" PersonId="DFL-OBJ-00011W">, frames like <Frame N="10001" T="...12.640" X="19.92" Y="-34.45" D="3.40" S="1.77" A="1.48" M="1"/> (25 Hz). Mid-file range 200,000,000 shows ball frames with Z, BallPossession, BallStatus.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_162828.jsonl`).
