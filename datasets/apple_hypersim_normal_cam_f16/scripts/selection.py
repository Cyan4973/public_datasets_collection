#!/usr/bin/env python3
"""Deterministic frame selection for apple_hypersim_normal_cam_f16.

Input: the pinned ``metadata_images_split_scene_v1.csv`` from apple/ml-hypersim.

Rule (one frame per selected scene):

1. Keep only rows with ``included_in_public_release == True`` (this drops the
   frames excluded as OUTSIDE VIEWING AREA or CONTENT FLAGGED FOR REMOVAL; the
   flagged frames are also physically absent from the scene zips).
2. Public scenes = scenes with at least one kept row, sorted by name (457 at
   the pinned commit; they are exactly the 457 zips listed by the upstream
   ``contrib/99991/download.py``).
3. Take ``N_SAMPLES`` scenes evenly spaced over that sorted list: index
   ``k * n_scenes // N_SAMPLES`` for ``k = 0 .. N_SAMPLES-1``.  The cap exists
   only because one full 768x1024x3 float16 frame is 4,718,592 bytes and the
   repository caps primary output at 1,000,000,000 bytes.
4. Camera: ``cam_00`` when it has kept frames, otherwise the lowest-numbered
   camera with kept frames (8 public scenes lack a public cam_00).
5. Frame: the kept frame ids of that camera, sorted ascending, element
   ``len // 2`` (mid-trajectory).

Usage: selection.py <split.csv>  -> TSV on stdout
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict

N_SAMPLES = 200
ZIP_URL = "https://docs-assets.developer.apple.com/ml-research/datasets/hypersim/v1/scenes/{scene}.zip"
MEMBER = "{scene}/images/scene_{camera}_geometry_hdf5/frame.{frame:04d}.normal_cam.hdf5"
COLUMNS = ["scene_name", "camera_name", "frame_id", "kept_frames_in_camera", "member_name", "zip_url"]


def select(csv_path: str) -> list[dict[str, str]]:
    kept: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        want = {"scene_name", "camera_name", "frame_id", "included_in_public_release"}
        if not want.issubset(reader.fieldnames or []):
            raise SystemExit(f"split CSV lacks columns {sorted(want - set(reader.fieldnames or []))}")
        for row in reader:
            flag = row["included_in_public_release"]
            if flag not in ("True", "False"):
                raise SystemExit(f"unexpected included_in_public_release value {flag!r}")
            if flag == "True":
                kept[row["scene_name"]][row["camera_name"]].append(int(row["frame_id"]))
    scenes = sorted(kept)
    if len(scenes) < N_SAMPLES:
        raise SystemExit(f"only {len(scenes)} public scenes, need {N_SAMPLES}")
    out = []
    for k in range(N_SAMPLES):
        scene = scenes[k * len(scenes) // N_SAMPLES]
        cams = kept[scene]
        camera = "cam_00" if cams.get("cam_00") else sorted(c for c in cams if cams[c])[0]
        frames = sorted(set(cams[camera]))
        frame = frames[len(frames) // 2]
        out.append({
            "scene_name": scene,
            "camera_name": camera,
            "frame_id": str(frame),
            "kept_frames_in_camera": str(len(frames)),
            "member_name": MEMBER.format(scene=scene, camera=camera, frame=frame),
            "zip_url": ZIP_URL.format(scene=scene),
        })
    if len({r["scene_name"] for r in out}) != N_SAMPLES:
        raise SystemExit("selection produced duplicate scenes")
    return out


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    rows = select(sys.argv[1])
    print("\t".join(COLUMNS))
    for row in rows:
        print("\t".join(row[c] for c in COLUMNS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
