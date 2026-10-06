"""Pinned identity of the HC18 Zenodo deposit (record 1327317, latest version
of concept record 1322000). Shared by build, verify and the self-test; the
decoding logic itself is implemented twice (hc18_decode.py for build,
hc18_verify.py for verify)."""
from __future__ import annotations

DATASET_ID = "zenodo_hc18_fetal_head_ultrasound_u8"
SERIES_ID = "hc18_fetal_head_bmode_u8"

RECORD_ID = 1327317
CONCEPT_RECORD_ID = 1322000

# Nominal frame size. The challenge page and paper say every image is 800x540,
# but 32 of the 1,334 published PNGs have slightly different native sizes
# (found by decoding the complete archives on 2026-10-06). Each exception is
# pinned exactly below; every other image must be 800x540. Images are emitted
# at their native size: nothing is cropped, padded or resampled.
WIDTH = 800
HEIGHT = 540
SIZE_EXCEPTIONS = {
    "training_set/139_HC.png": (786, 542),
    "training_set/188_HC.png": (782, 542),
    "training_set/208_HC.png": (794, 544),
    "training_set/216_HC.png": (738, 541),
    "training_set/234_HC.png": (780, 544),
    "training_set/276_2HC.png": (783, 541),
    "training_set/276_HC.png": (783, 543),
    "training_set/309_HC.png": (797, 541),
    "training_set/310_HC.png": (790, 539),
    "training_set/362_HC.png": (800, 542),
    "training_set/402_HC.png": (799, 563),
    "training_set/455_HC.png": (780, 539),
    "training_set/456_HC.png": (794, 543),
    "training_set/500_HC.png": (788, 545),
    "training_set/501_HC.png": (798, 541),
    "training_set/535_HC.png": (800, 542),
    "training_set/537_HC.png": (789, 540),
    "training_set/605_HC.png": (800, 542),
    "training_set/641_HC.png": (800, 542),
    "training_set/643_HC.png": (796, 542),
    "training_set/698_HC.png": (800, 542),
    "training_set/731_2HC.png": (789, 545),
    "training_set/731_3HC.png": (796, 544),
    "training_set/731_HC.png": (791, 544),
    "test_set/092_HC.png": (799, 544),
    "test_set/112_HC.png": (795, 542),
    "test_set/154_HC.png": (786, 544),
    "test_set/200_HC.png": (784, 544),
    "test_set/229_HC.png": (800, 543),
    "test_set/242_HC.png": (784, 545),
    "test_set/252_HC.png": (788, 541),
    "test_set/312_HC.png": (782, 541),
}
# Exact publication duplicate: the member's PNG file, annotation mask and CSV
# row are byte-identical to the original. Skipped; build and verify require its
# decoded pixels to equal the original's. Any other exact duplicate is fatal.
EXACT_DUPLICATES = {
    "training_set/392_2HC.png": "training_set/392_HC.png",
}
# Near-duplicates: the same acquired frame exported twice, identical except for
# a small region (at most 3.9 % of pixels, around the lower-right masked area).
# Found by scripts/near_duplicate_screen.py (all-pairs 24x16 thumbnail screen
# over the built samples, then full-resolution comparison). The later member in
# natural order is skipped. Build and verify require the same shape as the
# original and a differing-pixel fraction above 0 and below
# NEAR_DUPLICATE_MAX_DIFF_FRACTION. The closest pairs not listed here
# (795_HC/795_2HC, 780_HC/780_2HC) differ in 64 % and 59 % of pixels and are
# distinct frames.
NEAR_DUPLICATES = {
    "training_set/243_3HC.png": "training_set/243_HC.png",
    "training_set/788_2HC.png": "training_set/788_HC.png",
    "training_set/720_2HC.png": "training_set/720_HC.png",
    "training_set/507_2HC.png": "training_set/507_HC.png",
    "training_set/198_2HC.png": "training_set/198_HC.png",
    "training_set/392_3HC.png": "training_set/392_HC.png",
    "training_set/220_2HC.png": "training_set/220_HC.png",
    "test_set/280_HC.png": "test_set/263_HC.png",
}
NEAR_DUPLICATE_MAX_DIFF_FRACTION = 0.10
SKIPPED_MEMBERS = {**EXACT_DUPLICATES, **NEAR_DUPLICATES}
# Emitted totals: 1,334 published images minus the 9 skipped members above
# (all 800x540).
TOTAL_VALUES = 572299207


def expected_size(member: str) -> tuple[int, int]:
    """(width, height) pinned for one archive member path."""
    return SIZE_EXCEPTIONS.get(member, (WIDTH, HEIGHT))


# Each split: ZIP archive, member prefix, pixel-size CSV and its exact header.
SPLITS = [
    {
        "split": "training",
        "resource": "training_set_zip",
        "archive": "training_set.zip",
        "archive_bytes": 132926838,
        "archive_md5": "00eb8198b9a505b2b3a6dfc740382497",
        "cd_entries": 1999,
        "cd_offset": 132705556,
        "cd_size": 221260,
        "prefix": "training_set/",
        "images": 999,
        "images_stored": 944,
        "images_deflated": 55,
        "annotations": 999,
        "csv": "training_set_pixel_size_and_HC.csv",
        "csv_bytes": 33688,
        "csv_md5": "c0761518fece2bd2d2ad4218f2cd9777",
        "csv_header": ["filename", "pixel size(mm)", "head circumference (mm)"],
    },
    {
        "split": "test",
        "resource": "test_set_zip",
        "archive": "test_set.zip",
        "archive_bytes": 43518463,
        "archive_md5": "8402af5d137ef40a2888c1011ef3fe7e",
        "cd_entries": 336,
        "cd_offset": 43484515,
        "cd_size": 33926,
        "prefix": "test_set/",
        "images": 335,
        "images_stored": 312,
        "images_deflated": 23,
        "annotations": 0,
        "csv": "test_set_pixel_size.csv",
        "csv_bytes": 9096,
        "csv_md5": "8476dc198cc6542f26c57e87faeee033",
        "csv_header": ["filename", "pixel size(mm)"],
    },
]
PUBLISHED_IMAGES = sum(split["images"] for split in SPLITS)
TOTAL_IMAGES = PUBLISHED_IMAGES - len(SKIPPED_MEMBERS)

# Image member names: NNN_HC.png (first image of an exam) or NNN_kHC.png
# (k = 2..9, further images from the same exam). *_Annotation.png members are
# the sonographer ellipse masks (labels) and are never decoded.
IMAGE_NAME_PATTERN = r"^(\d{3})_(?:([2-9])HC|HC)\.png$"
ANNOTATION_NAME_PATTERN = r"^(\d{3})_(?:([2-9])HC|HC)_Annotation\.png$"

# Sanity bounds for the CSV pixel sizes (index metadata only). The challenge
# page and paper quote 0.052-0.326 mm, but the published CSVs actually span
# 0.04941 mm (training 022_HC.png) to 0.39328 mm (training), test 0.05256 to
# 0.37130 mm.
PIXEL_SIZE_MIN_MM = 0.04
PIXEL_SIZE_MAX_MM = 0.40

# Degeneracy guards applied identically by build and verify.
MIN_DISTINCT_VALUES = 64
MAX_MODAL_FRACTION = 0.90

# SHA-256 over "<sample file name>\t<sample sha256>\n" lines in index order.
# Pinned from the verified 2026-10-06 build; build and verify enforce it.
AGGREGATE_SHA256 = "ffd5dceb156129b58f990d5e8a8dd19d7ed034c7021e57d0b9bd8c3dc5171602"


def sample_name(split: dict, member_basename: str) -> str:
    stem = member_basename[: -len(".png")]
    return f"{split['split']}_{stem}.bin"


def natural_key(member_basename: str) -> tuple[int, int]:
    import re

    match = re.match(IMAGE_NAME_PATTERN, member_basename)
    if not match:
        raise ValueError(f"unexpected image member name {member_basename!r}")
    return int(match.group(1)), int(match.group(2) or 1)
