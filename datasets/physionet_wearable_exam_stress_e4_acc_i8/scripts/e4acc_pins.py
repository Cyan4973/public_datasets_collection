"""Pinned upstream files of PhysioNet wearable-exam-stress 1.0.0 used by the
physionet_wearable_exam_stress_e4_acc_i8 recipe.

Sizes come from HEAD requests and SHA-256 values from the release
SHA256SUMS.txt (probed 2026-10-08). The release is immutable (versioned path).
"""

DATASET_ID = "physionet_wearable_exam_stress_e4_acc_i8"
SERIES_ID = "e4_wrist_acc_xyz_i8"
RELEASE = "wearable-exam-stress/1.0.0"
S3_BASE_URL = "https://physionet-open.s3.amazonaws.com/wearable-exam-stress/1.0.0"
PHYSIONET_BASE_URL = "https://physionet.org/files/wearable-exam-stress/1.0.0"
PROJECT_PAGE_URL = "https://physionet.org/content/wearable-exam-stress/1.0.0/"

SHA256SUMS_BYTES = 22163
SHA256SUMS_SHA256 = "9b83f8414e3dc26b363d821614b9ae7a60ac8175d7231c43736f50fd2a3a7ed2"
SHA256SUMS_ENTRIES = 244
LICENSE_BYTES = 20402
LICENSE_SHA256 = "86c0ad300f6d380591298bc03652e30b81f65954bbf22435812bcfd46812ab06"

SAMPLE_RATE_HZ = 32
AXES = 3
VALUE_MIN = -128
VALUE_MAX = 127
EXAMS = ("midterm_1", "midterm_2", "Final")

# (subject, exam, release path, size_bytes, sha256), canonical order:
# subject number ascending, then midterm_1, midterm_2, Final.
ACC_FILES = (
    (1, "midterm_1", "data/S1/midterm_1/ACC.csv", 3457833, "0e603c111ef1d8deed5701cf12449a0dfa88b56680dba034e5adaa624ab4d5e4"),
    (1, "midterm_2", "data/S1/midterm_2/ACC.csv", 3442776, "b2d4549f573caf8dafd176678653630af029de06e2dd88efee9a44371b321153"),
    (1, "Final", "data/S1/Final/ACC.csv", 7066047, "a0a790b8f5610fa332cb3a2dc80c167a4461e7345705bfcd9beed1fc42f7fc93"),
    (2, "midterm_1", "data/S2/midterm_1/ACC.csv", 3467063, "afe019154a5374a193a57ff9e7ea811079938ba14d3ed77ae0aa233465081643"),
    (2, "midterm_2", "data/S2/midterm_2/ACC.csv", 3921057, "38c4c0918e99c7fd9d09e62bd004ac96e74066a4eb07f6c3842080f0285020e6"),
    (2, "Final", "data/S2/Final/ACC.csv", 8449584, "c95d7d05486e8244e74c6d98263cf64541d08db2e060f556140c899260e4b5dc"),
    (3, "midterm_1", "data/S3/midterm_1/ACC.csv", 4004028, "58193075619eb2f305891d43ac497ae53f54b472f75be5d5629b28063bdf3b6a"),
    (3, "midterm_2", "data/S3/midterm_2/ACC.csv", 3237419, "cb35e1db5aaba87de82d9b3c2d30d16f092ea45a1a52eaedecf411b56d8d2c43"),
    (3, "Final", "data/S3/Final/ACC.csv", 7994046, "1f2d38f57ff3da432fe1dccd2dd0860328478c44ecf551165ff3af5e121a08e9"),
    (4, "midterm_1", "data/S4/midterm_1/ACC.csv", 3786829, "ead9fecb5e300f407313430dd9e8f9cb396fb329e07adcc8215416efd098b9fe"),
    (4, "midterm_2", "data/S4/midterm_2/ACC.csv", 4227962, "e5b8b8268b1c8edfb0793e73f7b0d0e658437327652cc36fc24d81a25e4bc4a2"),
    (4, "Final", "data/S4/Final/ACC.csv", 5144998, "926cd1f3c6ae1aa90f42f5fc2d93726b70c7300e40287639bf540aeecb5a6444"),
    (5, "midterm_1", "data/S5/midterm_1/ACC.csv", 3708368, "453bca4ab8b16066bbbec5786e83f8077f6c39e9d4de207eafddfef92907717f"),
    (5, "midterm_2", "data/S5/midterm_2/ACC.csv", 3702416, "db30cfdc483015621657a13c86bfb293db266002e3a844a7abd9e75a4a900463"),
    (5, "Final", "data/S5/Final/ACC.csv", 4920182, "ed483ced16309e2dd94caaff6d9e724222b69e31c3c054d618be21dd0b6a82be"),
    (6, "midterm_1", "data/S6/midterm_1/ACC.csv", 3179658, "a7611951930fb77373ad66e0da4dc5a4a24d85837ee0506ed4128192a4f903e3"),
    (6, "midterm_2", "data/S6/midterm_2/ACC.csv", 4319251, "0b96c9537e58e4b631db9c2ffd1a596b40c5c4360b8f077e175d1ea2e8bfcc99"),
    (6, "Final", "data/S6/Final/ACC.csv", 7540547, "71b15514689b149d08bcb002845afa534d4ea88d4d93dccf9b4d2915af8d27c4"),
    (7, "midterm_1", "data/S7/midterm_1/ACC.csv", 3621727, "cda89a6b2b781ea070a0a4d3468e378e5a92d1c26dcbad86251e6e99f978e69a"),
    (7, "midterm_2", "data/S7/midterm_2/ACC.csv", 3378991, "e299466fc38530bf48876118c1d23df33c2afcde895afe5b83145c38f658d47e"),
    (7, "Final", "data/S7/Final/ACC.csv", 5581807, "0dee46e6b19a3947656844eb1cab71d5df58a477f56467e9511f4fbc0411c0ba"),
    (8, "midterm_1", "data/S8/midterm_1/ACC.csv", 3244752, "ca0d1fcdfa50ae3b7c08e35e6a00b8670a7573285843bbc4c4e332f60171edb2"),
    (8, "midterm_2", "data/S8/midterm_2/ACC.csv", 3102433, "11a5d7c72ea001590622fb388139231082743bdc31cc351fcc5bdc4fd236fc8d"),
    (8, "Final", "data/S8/Final/ACC.csv", 5725784, "d988a4564eb244b6e03d3bb4fb70b1e0acc1f15cecf46712575fa956402ec62b"),
    (9, "midterm_1", "data/S9/midterm_1/ACC.csv", 3887816, "fb586d52016d998a52e40b0053e92dc832ca787888510f178bac099a4016c0e3"),
    (9, "midterm_2", "data/S9/midterm_2/ACC.csv", 3887249, "0e6582a8e47e5c65e2177e4b2f40387c4a388ea3883491348a951e71c33462ff"),
    (9, "Final", "data/S9/Final/ACC.csv", 4621217, "9c19f292b518939d92aa75fa2dbc57ec70b3d42f69e570d54491965b88663830"),
    (10, "midterm_1", "data/S10/midterm_1/ACC.csv", 3796481, "0db353216eb9227867331ac624271a48342b4098c524f4f56b4a19d94688589e"),
    (10, "midterm_2", "data/S10/midterm_2/ACC.csv", 4206122, "08ab43cdc60edb740e733885d81d7b25110348817463c126b3824d18e19dd881"),
    (10, "Final", "data/S10/Final/ACC.csv", 7142879, "c84a36efd75860826b32bb5b3f8f5ba5c252cff4ccb74afe38ba32fd7948a62a"),
)

ACC_TOTAL_BYTES = sum(row[3] for row in ACC_FILES)
assert len(ACC_FILES) == 30
assert ACC_TOTAL_BYTES == 137767322


def session_id(subject, exam):
    return f"S{subject}_{exam}"


def local_name(subject, exam):
    """Flat local file name under the download directory."""
    return f"S{subject}_{exam}_ACC.csv"
