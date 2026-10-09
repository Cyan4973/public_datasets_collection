# GoldenCheetah OpenData (CC0, OSF 6hfpz): Per-Second Bike-Computer Pedalling Cadence (rpm) per Cycling Activity UInt8

- Candidate id: `goldencheetah_opendata_cycling_cadence_u8`
- Width: uint8
- Quantity: Pedalling cadence in revolutions per minute, recorded at 1 Hz by cyclists' bike computers and crank or pedal cadence sensors: integer rpm, 0 when coasting, typically 60-120.
- Source: https://osf.io/6hfpz/
- Resources: https://api.osf.io/v2/nodes/6hfpz/files/osfstorage/, https://osf.io/download/5e7330934a60a504c2bb2870/, https://github.com/GoldenCheetah/OpenData/blob/master/README.md
- License: CC0 1.0 Universal (OSF project license)
- License evidence: https://api.osf.io/v2/nodes/6hfpz/
- License quote: OSF node 6hfpz 'GoldenCheetah OpenData Project' node_license -> https://api.osf.io/v2/licenses/563c1cf88c5e4a3877f9e96c/ name: "CC0 1.0 Universal"; README: "The data is entirely anonymised, no personally identifiable information is stored or made available."
- Natural record: One cycling activity: one CSV member '<date>.csv' inside an athlete zip. Columns are secs,km,power,hr,cad,alt at 1 Hz; take the cad column as uint8. Only activities whose summary JSON entry has sport=='Bike' and a 'C' (cadence present) in its data flag string are used. Medians are about 2,000-4,000 values per activity.
- Estimated samples: 40,000
- Estimated primary values: 110,000,000
- Estimated download bytes: 1,300,000,000
- Estimated primary bytes: 110,000,000
- Decode path: Page the OSF files API with page[size]=100 (use curl -g because of the brackets) to list the 6,614 athlete zips with sizes and sha256. Choose a deterministic bounded subset, e.g. the first N by name until about 1.2 GB, and download via the osf.io/download/<id>/ redirect (supports Range and resume). In Python, zipfile reads the {guid}.json RIDES list (date, sport, data flags) and each matching CSV. Parse cad as an integer, require 0..255, and reject or skip non-integer or out-of-range activities per a documented policy. Pure stdlib.
- Novelty kind: new_quantity
- Measurement type: exercise_cadence
- Instrument line: bike_computer_cadence_sensor
- Archive collection: osf.io/6hfpz
- Novelty evidence: novelty.py --url https://osf.io/6hfpz/ --terms goldencheetah cadence cycling: no URL, ledger, registry or downstream match. 'cadence' only hits as a word for sampling rate in other recipes. No exercise-cadence family exists. The nearest 8-bit families are zenodo_mturk_fitbit_heartrate_u8 (wrist HR, smooth 36-203) and openf1/AEGIS vehicle telemetry. Cadence is a mechanical human-motor signal with coasting zeros and noisy 60-120 rpm plateaus.
- Homogeneity: Cycling only (sport=='Bike'). Exclude Run and other sports, whose cadence is steps per minute and can exceed 255. One unit (rpm, integer, 1 Hz GoldenCheetah resampled CSV). One sample per activity. Leave out power, HR, altitude and speed from the same files: heart rate would duplicate wearable_heart_rate and is the same source file. Athletes use mixed sensor brands, but the quantity, unit and 1 Hz lattice are uniform.
- Risks: (1) The extraction ratio is about 10-12 download bytes per kept byte (multi-column CSV in zips), but absolute kept signal is large (about 100 MB) and no leaner source exists. (2) Some files may hold float or empty cadence cells or spikes up to 255. Define the policy as skip activity or treat empty as missing, then verify. (3) Large athlete zips (up to 227 MB) can dominate, so consider a per-athlete activity cap or skip zips over about 60 MB. (4) Demographics (gender, yob) are in the JSON; do not emit them. (5) The OSF storage redirect URLs are signed and expire, so always resolve through osf.io/download/<id>/.
- Probe evidence: The OSF API shows the node is public with license CC0 1.0 Universal and 6,614 files. A sample of 200 zips had median 8.8 MB, mean 20.6 MB and max 227 MB. Probes on athlete zip 5e7330934a60a504c2bb2870 (3,852,578 B): a range GET of the last 64 KB (206) parsed the central directory (140 members: 1 JSON + 139 activity CSVs of about 45-105 KB). A range-fetched first CSV member (14,795 B compressed) inflated to 1,978 rows with header 'secs,km,power,hr,cad,alt' and integer cadence (75,75,76,…,70). A range-fetched JSON head shows RIDES entries with "sport":"Bike" and "data":"TDSP-C-AGL-E---" flags, plus metrics like max_cadence 117.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_230754.jsonl`).
