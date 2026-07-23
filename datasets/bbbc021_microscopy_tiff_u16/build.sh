#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="bbbc021_microscopy_tiff_u16"
SERIES_ID="bbbc021_microscopy_u16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1

# Bounded subset to stay under 1GB cap: keep first 300 TIFFs sorted (~780 MB raw)
# numeric16_extract.extract_archives would otherwise unzip all 720 -> 1.88 GB > cap,
# so we pre-extract a bounded subset and hide the zip outside download_dir during build.
python3 - <<'PY'
import zipfile, shutil, os
from pathlib import Path
repo_root = Path(os.environ.get("REPO_ROOT", "."))
data_dir = os.environ.get("DATA_DIR", ".data")
download_dir = repo_root / data_dir / "downloads" / "bbbc021_microscopy_tiff_u16"
extracted_dir = repo_root / data_dir / "extracted" / "bbbc021_microscopy_tiff_u16"
hidden_dir = Path("/tmp/bbbc021_hidden")
# Clean extracted and hidden
if extracted_dir.exists():
    shutil.rmtree(extracted_dir)
extracted_dir.mkdir(parents=True, exist_ok=True)
hidden_dir.mkdir(parents=True, exist_ok=True)
# Ensure zip is back in download_dir (may be in hidden)
for p in hidden_dir.glob("*.zip"):
    dest = download_dir / p.name
    if not dest.exists():
        shutil.move(str(p), str(dest))
zips = sorted(download_dir.glob("*.zip"))
if not zips:
    raise SystemExit(f"no zip found in {download_dir}")
z = zips[0]
with zipfile.ZipFile(z) as zf:
    infos = [info for info in zf.infolist() if not info.is_dir() and info.filename.lower().endswith(('.tif','.tiff'))]
    infos_sorted = sorted(infos, key=lambda i: i.filename)
    keep = infos_sorted[:300]
    print(f"zip {z.name} contains {len(infos_sorted)} tiffs, keeping {len(keep)}")
    for info in keep:
        zf.extract(info, extracted_dir)
# Hide zip outside download_dir so extract_archives finds nothing
for zp in download_dir.glob("*.zip"):
    dest = hidden_dir / zp.name
    if not dest.exists():
        shutil.move(str(zp), str(dest))
    else:
        zp.unlink()
print("bounded extraction done, zip hidden outside")
PY

python3 "$REPO_ROOT/tools/numeric16_extract.py" build --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --dataset-id "$DATASET_ID" --series-id "$SERIES_ID" --format tiff --max-primary-bytes 1000000000

# Restore zip
python3 - <<'PY'
import shutil
from pathlib import Path
import os
repo_root = Path(os.environ.get("REPO_ROOT", "."))
data_dir = os.environ.get("DATA_DIR", ".data")
download_dir = repo_root / data_dir / "downloads" / "bbbc021_microscopy_tiff_u16"
hidden_dir = Path("/tmp/bbbc021_hidden")
for zp in hidden_dir.glob("*.zip"):
    dest = download_dir / zp.name
    if not dest.exists():
        shutil.move(str(zp), str(dest))
PY


