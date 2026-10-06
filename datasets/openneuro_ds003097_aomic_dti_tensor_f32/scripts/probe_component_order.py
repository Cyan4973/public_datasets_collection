#!/usr/bin/env python3
"""Probe that documents how the tensor component order was resolved.

Not part of download/build/verify. Run on one participant's published files
(fetched separately into a scratch directory, e.g. for sub-0001):

  B=https://s3.amazonaws.com/openneuro.org/ds003097/derivatives/dwipreproc/sub-0001/dwi
  for f in diffmodel FA EVECS; do
    curl -fsSLO "$B/sub-0001_model-DTI_desc-WLS_$f.nii.gz"
  done
  python3 probe_component_order.py sub-0001_model-DTI_desc-WLS_{diffmodel,FA,EVECS}.nii.gz

Step 1 locates the diagonal elements: FA recomputed from tensor invariants
(trace and Frobenius norm) must match the published FA map. This separates
MRtrix3 (xx,yy,zz,xy,xz,yz), FSL dtifit (xx,xy,xz,yy,yz,zz) and dipy
lower-triangular (xx,xy,yy,xz,yz,zz) layouts. Step 2 fixes the off-diagonal
order, to which FA is invariant: the principal eigenvector of the tensor must
be parallel to the published first-eigenvector map (EVECS).

Observed for sub-0001 (2026-10-05): MRtrix3 layout FA max abs error 5.8e-8
over 172,959 brain voxels (FSL 1.18, dipy 1.00); off-diagonals (xy,xz,yz) at
volumes (3,4,5) give mean |cos| 0.99984 versus 0.72-0.84 for the other five
permutations.
"""

from __future__ import annotations

import gzip
import itertools
import math
import sys
from array import array

N = 112 * 112 * 60


def values(path: str) -> array:
    data = gzip.decompress(open(path, "rb").read())
    out = array("f")
    out.frombytes(data[352:])
    if sys.byteorder != "little":
        out.byteswap()
    return out


def principal(m: list[list[float]]) -> list[float]:
    shift = sum(abs(m[i][j]) for i in range(3) for j in range(3))
    a = [[m[i][j] + (shift if i == j else 0.0) for j in range(3)] for i in range(3)]
    x = [1.0, 0.7, 0.3]
    for _ in range(200):
        y = [sum(a[i][j] * x[j] for j in range(3)) for i in range(3)]
        norm = math.sqrt(sum(t * t for t in y))
        x = [t / norm for t in y]
    return x


def main() -> None:
    tensor, fa, evecs = (values(p) for p in sys.argv[1:4])
    comps = [tensor[c * N : (c + 1) * N] for c in range(6)]
    layouts = {
        "mrtrix3 xx,yy,zz,xy,xz,yz": (0, 1, 2, 3, 4, 5),
        "fsl xx,xy,xz,yy,yz,zz": (0, 3, 5, 1, 2, 4),
        "dipy xx,xy,yy,xz,yz,zz": (0, 2, 5, 1, 3, 4),
    }
    for name, (ixx, iyy, izz, ixy, ixz, iyz) in layouts.items():
        worst = 0.0
        for v in range(N):
            xx, yy, zz = comps[ixx][v], comps[iyy][v], comps[izz][v]
            xy, xz, yz = comps[ixy][v], comps[ixz][v], comps[iyz][v]
            t1 = xx + yy + zz
            t2 = xx * xx + yy * yy + zz * zz + 2 * (xy * xy + xz * xz + yz * yz)
            calc = math.sqrt(max(0.0, 1.5 - 0.5 * t1 * t1 / t2)) if t2 > 0 else 0.0
            worst = max(worst, abs(calc - fa[v]))
        print(f"FA check {name}: max abs error {worst:.3g}")
    ev = [evecs[c * N : (c + 1) * N] for c in range(3)]
    voxels = [v for v in range(N) if fa[v] > 0.4][::20]
    for perm in itertools.permutations((3, 4, 5)):
        total = 0.0
        for v in voxels:
            xy, xz, yz = (comps[i][v] for i in perm)
            p = principal([[comps[0][v], xy, xz], [xy, comps[1][v], yz], [xz, yz, comps[2][v]]])
            e = [ev[k][v] for k in range(3)]
            norm = math.sqrt(sum(t * t for t in e))
            total += abs(sum(p[k] * e[k] for k in range(3))) / norm
        print(f"EVECS check off-diagonal volumes (xy,xz,yz)={perm}: mean |cos| {total / len(voxels):.6f}")


if __name__ == "__main__":
    main()
