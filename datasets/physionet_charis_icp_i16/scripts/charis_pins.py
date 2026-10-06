"""Pinned facts for PhysioNet CHARIS database 1.0.0 (charisdb).

Resolved on 2026-10-05 from the anonymous S3 listing of
s3://physionet-open/charisdb/1.0.0/, the release SHA256SUMS.txt, and the 13
WFDB headers. Shared by download, build and verify; the decoders themselves
are independent (charis_build.py and charis_verify.py).
"""
from __future__ import annotations

DATASET_ID = "physionet_charis_icp_i16"
SERIES_ID = "charis_icp_channel_adc_i16"
NATURAL_RECORD_KIND = "complete_charis_patient_recording_icp_channel"
BASE_URL = "https://physionet-open.s3.amazonaws.com/charisdb/1.0.0"
LICENSE_PAGE_URL = "https://physionet.org/content/charisdb/1.0.0/"

SHA256SUMS_BYTES = 2083
SHA256SUMS_SHA256 = "13a392e1dfbc1a3c3793c67a33b4fae4a702908defc319952a3759d7ff6e91da"
RECORDS_BYTES = 108
RECORDS_SHA256 = "5ef47a7812aeafb13f10f64404b94ef3706777fdd01a0a90060bea2528e23aef"

SIGNALS = ("ABP", "ECG", "ICP")
ICP_INDEX = 2
SAMPLING_HZ = 50
WINDOW_SAMPLES = 3000  # 60 s diagnostic windows (descriptive only, never used to filter)

# Diagnostic thresholds in mmHg, applied through each record's header gain/baseline.
# Per-value: count codes outside [VALUE_LOW_MMHG, VALUE_HIGH_MMHG].
# Per 60 s window (mutually exclusive classes, by window median m, peak-to-peak
# p2p and 5th-95th percentile spread s, all in mmHg):
#   m < -10                         -> negative
#   -10 <= m <= 50, p2p < 1         -> flat_icp_range
#   -10 <= m <= 50, p2p >= 1, r1 >= 0.5 -> plausible_icp (pressure waveform present)
#   -10 <= m <= 50, p2p >= 1, r1 < 0.5  -> icp_range_noise (white noise around a level)
#   50 < m <= 250, s >= 20          -> high_pulsatile (arterial-like waveform)
#   50 < m <= 250, s < 2            -> high_flat (pegged output)
#   50 < m <= 250, otherwise        -> high_other
#   m > 250                         -> very_high (crosstalk / out of range)
VALUE_LOW_MMHG = -10.0
VALUE_HIGH_MMHG = 100.0
WINDOW_HIGH_MEDIAN_MMHG = 50.0
WINDOW_VERY_HIGH_MEDIAN_MMHG = 250.0
WINDOW_FLAT_P2P_MMHG = 1.0
WINDOW_PULSATILE_SPREAD_MMHG = 20.0
WINDOW_PEGGED_SPREAD_MMHG = 2.0
# Waveform-presence test for in-band windows: lag-1 autocorrelation r1 of the
# window's codes, evaluated exactly in integers as
#   y_i = n*x_i - sum(x);  waveform iff 2*sum_{i<n-1} y_i*y_{i+1} >= sum_i y_i^2
# (equivalent to r1 >= 0.5). For a smooth signal plus white noise,
# r1 ~ S/(S+N), so 0.5 means waveform power >= sample-noise power. Real ICP
# windows sit at r1 >= 0.9; white noise around a level sits near 0.
WAVEFORM_MIN_LAG1_AUTOCORR = 0.5
WINDOW_CLASSES = (
    "plausible_icp",
    "icp_range_noise",
    "flat_icp_range",
    "negative",
    "high_pulsatile",
    "high_flat",
    "high_other",
    "very_high",
)
# Adjacent ICP codes differing by more than half the int16 span: the published
# data wraps modulo 65536 at the rails in a few artifact stretches.
WRAP_JUMP_CODES = 32768

# (record, nsamp, dat_bytes, dat_sha256, hea_bytes, hea_sha256,
#  icp_gain_text, icp_baseline, icp_header_checksum)
RECORDS = (
    ("charis1", 12239851, 73439106, "7ffc3614913c4205bb9322d8e9870b43244e6047901851d9894aa23781da7a28", 247, "5112c06bccc122c614f19efa599be5c2b7647b7adbab8712994d8420b27a04bc", "94.8784", -2316, 27046),
    ("charis2", 67499794, 404998764, "0211dc70330f9af1b3d2f374be251c8e30ecc8db628256efdd649fae45951d0c", 243, "9b7bba88ef245f213a60082bcae40727a06e9b3820f82445c768f5d673034f76", "82.1325", -310, 7012),
    ("charis3", 17095224, 102571344, "cf6cb7aa81b8ff8516c67248725d2d0ecaa08d5970f18ec1156bd3904ccc38db", 241, "1a46b4eaf2af4bc6aae9cc2a45761ccf7c9673df87b9114a7779815ecd75a925", "80.2357", 64, -10279),
    ("charis4", 7199999, 43199994, "4df6c0aece615798eeb3790855714353a49c7a4679f6aa6fc533349fb29c10fd", 235, "26f461b6f775bf60654766a34ae8127eec063bb000f9300648ca75001d615569", "84.0552", -5, 21911),
    ("charis5", 35999722, 215998332, "4aeef4ec3944594a243bbf72bc42cbb8c42d0a5d300f089e76445d1dae1e376c", 240, "aabac2ac2caeaff56fd1872b81dd9ae5f8ad423eda95de96fc3b7b6887f497ec", "83.1953", -609, -10810),
    ("charis6", 8279982, 49679892, "ec941ac6cba0024837c966ed494c0da697b69a0535b987368cb1326199da93ea", 236, "c5efa9367b564369ba30469e10f59b4c38ec48cff377b052202acc04777a1085", "82.3123", -212, 10649),
    ("charis7", 24180734, 145084404, "78614673069830c3203b79d87b3f07e00e36191a62e9c0652a5fcba848304ebe", 224, "bf0606b2a405487b13b4f6db7d293e1d3c9e36ee3caadb093d4e3e02e01697c4", "98.0796", -2437, -7632),
    ("charis8", 17169957, 103019742, "5cc8be06a70a2d45d3772adc37f1969c4ea0e357b12f4355dbd60fb6a632b6b2", 179, "15fccc477e537070eebe91c336c28749c15384905e91d953ec9a0a2dce28a885", "83.0946", 172, -4631),
    ("charis9", 30779979, 184679874, "d6382984066f543c74128fee95f59bddadbc17c59da33a8969b6761e12e674ce", 260, "0bafe2fdfe96e29800878b730f62891a07469524023a806830cc40bf75efb5e8", "129.2474", -13789, -35),
    ("charis10", 21278773, 127672638, "2e06ea855d9525194f54a6aa756e35266659cf86c69ca80f1efce9375b779434", 181, "dac3f729e69fb7a3fd97d42ad640077c9a3993a4d95684b09cb18741cc69dfd2", "80.2506", -179, -17898),
    ("charis11", 17328390, 103970340, "b7f6eac4a1e8294d5b33f6670f96c6ebdd6319292b5d5f523bdeab8ad782ec5a", 237, "c395cb4d9b771160966e8e7d84a48ac4d1d2ebc51159f9ce355e01ff447e3d4f", "85.8882", -576, 9007),
    ("charis12", 20545133, 123270798, "f6903254546567fd4b87b49cc89026fcc5b45494e5d199ced6179a8eab8a05dd", 245, "d911d39e97099a2478282d5541f1a4443a30af46fbace87709723733d64e25ad", "60.8182", -392, 9467),
    ("charis13", 14219956, 85319736, "1aa593a4cbda27c1c020261310604bd6a35075bfc5b540ef15d673b09720e499", 245, "8f602be7424123a76c9f875eee5f7e0f3b75008a2969519bed29044c3cda232c", "80.2781", -3, 27623),
)

EXPECTED_RECORD_SET = {row[0] for row in RECORDS}

# Records whose ICP channel is majority non-ICP (full-record diagnostics,
# 60 s window classes). Their headers are still fetched and checked, and their
# SHA256SUMS entries are still compared with the pins, but their .dat files are
# neither downloaded nor emitted.
EXCLUDED_RECORDS = {
    "charis8": (
        "47.7% plausible-ICP windows; 43.3% arterial blood pressure on the ICP input while ABP reads "
        "about 0 mmHg, 4.1% flat and 3.4% ICP-band noise."
    ),
    "charis12": (
        "38.2% plausible-ICP windows; 57.5% of windows are in the ICP band but white noise around a level "
        "(lag-1 autocorrelation < 0.5) with no cardiac component while ABP is pulsatile; also the only "
        "unscaled native-lattice record (stretch 1.0)."
    ),
    "charis10": (
        "20.0% plausible-ICP windows; pegged output at about 101 mmHg (38.4% of windows), "
        ">250 mmHg crosstalk (14.3%) and flat/zero output (10.6%)."
    ),
    "charis9": (
        "8.6% plausible-ICP windows under the waveform test (40.7% without it; 32.1% are ICP-band noise); "
        "56.3% of windows carry arterial blood pressure on the ICP input "
        "while the ABP channel reads about 0 mmHg; header note 'Intermittent, discontinuous ICP signal'; "
        "outlier stretch 2.125 with baseline -13789."
    ),
}
KEPT_RECORDS = tuple(row[0] for row in RECORDS if row[0] not in EXCLUDED_RECORDS)
MIN_KEPT_PLAUSIBLE_FRACTION = 0.5

# Native monitor quantization: the excluded charis12's ICP and ABP headers,
# 60.8182(-392)/mmHg, are the unscaled record, and every ECG gain (6081.5219 or
# 6081.8245 per mV) is on the same scale. All 9 kept records' ICP and ABP channels
# were auto-scaled by the publisher to the full int16 range (exactly one +32767
# and one -32767 per channel).
NATIVE_GAIN_PER_MMHG = 60.8182
UNUSED_CODE_BAND_MMHG = 40.0

EXPECTED_DAT_BYTES_ALL = 1_762_904_964
EXPECTED_DAT_BYTES = 1_224_261_912  # kept records only (the downloaded .dat files)
EXPECTED_HEA_BYTES = 3_013
EXPECTED_PRIMARY_VALUES = 204_043_652
EXPECTED_PRIMARY_BYTES = 408_087_304
EXPECTED_MEDIAN_VALUES = 17_095_224  # charis3, index 4 of 9

assert set(EXCLUDED_RECORDS) <= EXPECTED_RECORD_SET and len(KEPT_RECORDS) == 9
assert sum(row[2] for row in RECORDS) == EXPECTED_DAT_BYTES_ALL
assert sum(row[2] for row in RECORDS if row[0] in KEPT_RECORDS) == EXPECTED_DAT_BYTES
assert sum(row[4] for row in RECORDS) == EXPECTED_HEA_BYTES
assert sum(row[1] for row in RECORDS if row[0] in KEPT_RECORDS) == EXPECTED_PRIMARY_VALUES
assert EXPECTED_PRIMARY_BYTES == 2 * EXPECTED_PRIMARY_VALUES
assert all(row[2] == row[1] * 6 for row in RECORDS)
assert sorted(row[1] for row in RECORDS if row[0] in KEPT_RECORDS)[len(KEPT_RECORDS) // 2] == EXPECTED_MEDIAN_VALUES


def record_rows():
    """All 13 records in canonical numeric order (RECORDS upstream lists charis10 first)."""
    return [
        {
            "record_id": row[0],
            "nsamp": row[1],
            "dat_bytes": row[2],
            "dat_sha256": row[3],
            "hea_bytes": row[4],
            "hea_sha256": row[5],
            "icp_gain_text": row[6],
            "icp_baseline": row[7],
            "icp_header_checksum": row[8],
            "excluded": row[0] in EXCLUDED_RECORDS,
        }
        for row in RECORDS
    ]


def kept_record_rows():
    """The 9 emitted records in canonical order: charis1-7, charis11, charis13."""
    return [row for row in record_rows() if not row["excluded"]]


def unused_code_bounds(gain: float, baseline: int) -> tuple[int, int]:
    """Inclusive integer code range for 0..40 mmHg under the header calibration."""
    import math

    return baseline, math.floor(baseline + UNUSED_CODE_BAND_MMHG * gain)
