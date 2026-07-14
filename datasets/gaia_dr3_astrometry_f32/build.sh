#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gaia_dr3_astrometry_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
import gzip, json, os, shutil, sys
from array import array
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"]); data_dir = os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"]); filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"]); samples_dir = Path(os.environ["SAMPLES_DIR"])

# Each series is one coherent astrometric quantity from the Gaia DR3 five-parameter
# solution. pmra/pmdec are distinct axes, so they are separate series.
SERIES = [
    ("parallax", "gaia_parallax_mas_f32"),
    ("pmra", "gaia_pmra_masyr_f32"),
    ("pmdec", "gaia_pmdec_masyr_f32"),
]
little = sys.byteorder == "little"

files = sorted(download_dir.glob("*.csv.gz"))
if not files:
    raise SystemExit(f"no *.csv.gz in {download_dir}")

shutil.rmtree(samples_dir, ignore_errors=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
inventory = []
for fi, src in enumerate(files):
    part = f"part{fi:02d}"
    cols = {name: array("f") for name, _ in SERIES}
    nrows = 0
    malformed = 0
    # Gaia bulk files are ECSV: a long '#'-comment YAML preamble, then the header,
    # then plain comma-separated data. Parse line-by-line (not csv.reader) so the
    # preamble's embedded quotes/commas cannot span into the real header, and split
    # the numeric data rows on commas (these columns never contain quoted commas).
    with gzip.open(src, "rt", encoding="utf-8") as fh:
        header = None
        for line in fh:
            if line.startswith("#"):
                continue
            header = line.rstrip("\n").split(",")
            break
        if header is None:
            raise SystemExit(f"{src.name}: no header")
        try:
            idx = {name: header.index(name) for name, _ in SERIES}
        except ValueError as e:
            raise SystemExit(f"{src.name}: missing column ({e})")
        ncol = len(header)
        for line in fh:
            if not line or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split(",")
            if len(fields) != ncol:
                malformed += 1
                continue
            nrows += 1
            for name, _ in SERIES:
                v = fields[idx[name]].strip()
                if v == "" or v.lower() == "null":
                    continue
                try:
                    cols[name].append(float(v))
                except ValueError:
                    continue
    if malformed:
        print(f"  {src.name}: skipped {malformed} malformed rows (field count != {ncol})")
    inventory.append((part, src.name, nrows))
    for name, sid in SERIES:
        a = cols[name]
        if len(a) == 0:
            raise SystemExit(f"empty series {sid} in {src.name}")
        smin = min(a)
        smax = max(a)
        if smin == smax:
            raise SystemExit(f"constant series {sid} in {src.name}")
        w = array("f", a)
        if not little:
            w.byteswap()
        outdir = samples_dir / sid
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / f"{part}.bin"
        out.write_bytes(w.tobytes())
        size = out.stat().st_size
        rows.append({
            "dataset_id": "gaia_dr3_astrometry_f32",
            "series_id": sid,
            "role": "primary",
            "part": part,
            "source_file": src.name,
            "sample_path": str(out.relative_to(repo / data_dir)),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": size,
            "value_count": len(a),
            "min": smin,
            "max": smax,
        })

(filter_dir / "inventory.tsv").write_text(
    "part\tsource_file\trow_count\n" + "".join(f"{p}\t{f}\t{c}\n" for p, f, c in inventory),
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, sort_keys=True) + "\n")
total = sum(r["value_count"] for r in rows)
print(f"wrote {len(rows)} samples from {len(files)} file(s), {total} primary f32 values")
for p, f, c in inventory:
    print(f"  {p} {f}: {c} rows")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
