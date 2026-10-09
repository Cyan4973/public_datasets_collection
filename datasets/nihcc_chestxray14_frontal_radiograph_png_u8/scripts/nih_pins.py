"""Pinned constants for the NIH ChestX-ray14 8-bit radiograph recipe.

Shared by download validation, build and verify. Only constants live here; the
build-side and verify-side decoders are written independently.
"""
from __future__ import annotations

DATASET_ID = "nihcc_chestxray14_frontal_radiograph_png_u8"
SERIES_ID = "chestxray14_frontal_radiograph_u8"

STATIC_URL_BASE = "https://nihcc.box.com/shared/static/"

# Bytes fetched from the start of every tarball (HTTP Range 0..PREFIX_BYTES-1).
# At ~410 KB per PNG this holds about 34 whole tar members per tarball.
PREFIX_BYTES = 14 * 1024 * 1024

# (tarball name, Box static-link hash, full size from Content-Range,
#  full-file MD5 published in FAQ_CHESTXRAY.pdf Q07 for reference only)
TARBALLS = [
    ("images_001.tar.gz", "vfk49d74nhbxq3nqjg0900w5nvkorp5c", 2008470987, "fe8ed0a6961412fddcbb3603c11b3698"),
    ("images_002.tar.gz", "i28rlmbvmfjbl8p2n3ril0pptcmcu9d1", 3952623504, "ab07a2d7cbe6f65ddd97b4ed7bde10bf"),
    ("images_003.tar.gz", "f1t00wrtdk94satdfb9olcolqx20z2jp", 3929234850, "2301d03bde4c246388bad3876965d574"),
    ("images_004.tar.gz", "0aowwzs5lhjrceb3qp67ahp0rd1l1etg", 3838903983, "9f1b7f5aae01b13f4bc8e2c44a4b8ef6"),
    ("images_005.tar.gz", "v5e3goj22zr6h8tzualxfsqlqaygfbsn", 3935496531, "1861f3cd0ef7734df8104f2b0309023b"),
    ("images_006.tar.gz", "asi7ikud9jwnkrnkj99jnpfkjdes7l6l", 3986301172, "456b53a8b351afd92a35bc41444c58c8"),
    ("images_007.tar.gz", "jn1b4mw4n6lnh74ovmcjb8y48h8xj07n", 4016328426, "1075121ea20a137b87f290d6a4a5965e"),
    ("images_008.tar.gz", "tvpxmn7qyrgl0w8wfh9kqfjskv6nmm1j", 4018347353, "b61f34cec3aa69f295fbb593cbd9d443"),
    ("images_009.tar.gz", "upyy3ml7qdumlgk2rfcvlb9k6gvqq2pj", 4111327929, "442a3caa61ae9b64e61c561294d1e183"),
    ("images_010.tar.gz", "l6nilvfa9cg3s28tqv1qc1olm3gnz54p", 4181556296, "09ec81c4c31e32858ad8cf965c494b74"),
    ("images_011.tar.gz", "hhq8fkdgvcari67vfhs7ppg2w6ni4jze", 4187084020, "499aefc67207a5a97692424cf5dbeed5"),
    ("images_012.tar.gz", "ioqwiy20ihqwyr8pf4c24eazhh281pbu", 2914187733, "dc9fda1757c2de0032b63347a7d2895c"),
]


def prefix_name(tarball: str) -> str:
    return tarball.replace(".tar.gz", f".prefix{PREFIX_BYTES}.tar.gz")


# SHA-256 of each downloaded prefix, pinned from the 2026-10-08 download; download.sh, build and verify enforce them.
PREFIX_SHA256: dict[str, str] = {
    "images_001.tar.gz": "02c6040f8774c7ce911be9518ea92a44a3ba43ef28ae30a40e0451758eb361b0",
    "images_002.tar.gz": "1d073b875493182e8ab4e1143e7787527d9dcb89c66707cb7a9152e17636a03b",
    "images_003.tar.gz": "fe2adc80dfb9be0121fb80b63ad53a473d2f0c11e5d782b468e8723c14dcf675",
    "images_004.tar.gz": "d1e61fa70289b5b1ee6ba294ed49f46a0a5a15eedbf8eafc57b4c51720777e6b",
    "images_005.tar.gz": "420fd6b66e64d4f1cda606b71226f9439f091e49c22b786509e7522a74f950ac",
    "images_006.tar.gz": "95ca34596ecda2d71564574b707f79bc29f148bd45f243d95c949adaaaa972e9",
    "images_007.tar.gz": "88864e3d8f66f0561c9d8a463bb4e6807b978eab179f5bcdbc2bc54d3624cfd2",
    "images_008.tar.gz": "a0d034a94130efe0e9852b96f007332b21d56c23718e700775813059012e42ba",
    "images_009.tar.gz": "f0f5092715ed2f9df02429c42e00ef3f144cc296f5ca2f5bfa4aecfb45c57b55",
    "images_010.tar.gz": "1f0a5b677c2a0a2359d2cc09869e07d0f8207efa2453b5736eff6da4f53f82a0",
    "images_011.tar.gz": "de6142f5e5ede8bdf28349a8ee8eeda0dd63a38a2741524245ee895002e89a28",
    "images_012.tar.gz": "97cde53fd8f04ec576220f9cba4c9bac3eb4aa3db6d34b71b6c65e016d0c3c3f",
}

FAQ_URL = (
    "https://nihcc.app.box.com/index.php?rm=box_download_shared_file"
    "&vanity_name=ChestXray-NIHCC&file_id=f_249502714403"
)
FAQ_NAME = "FAQ_CHESTXRAY.pdf"
FAQ_BYTES = 72223
FAQ_SHA256 = "674665256e6a14c8ebaa93648f438c2b4ca21205167839559bab3ecc89b6b83a"
FAQ_LICENSE_SENTENCE = (
    "The usage of the data set is unrestricted. But you should provide the link to our original "
    "download site, acknowledge the NIH Clinical Center and provide a citation to our CVPR 2017 paper."
)

WIDTH = 1024
HEIGHT = 1024
MEMBER_NAME_PATTERN = r"images/\d{8}_\d{3}\.png"

# Minimum number of whole tar members a prefix must contain (download check).
MIN_MEMBERS_PER_PREFIX = 20

# Degeneracy thresholds (build and verify alike).
MIN_DISTINCT_VALUES = 64
MAX_MODAL_FRACTION = 0.90

# Realized totals, pinned from the verified 2026-10-08 build.
TOTAL_SAMPLES = 430
AGGREGATE_SHA256 = "31787da346e9612163e226e9b736af2f24bc8818c71806200874f34604ef65cd"


def sample_name(tarball: str, member: str) -> str:
    """images_001.tar.gz + images/00001075_000.png -> images_001_00001075_000.bin"""
    stem = tarball[: -len(".tar.gz")]
    base = member.rsplit("/", 1)[-1][: -len(".png")]
    return f"{stem}_{base}.bin"
