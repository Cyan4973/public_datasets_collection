#!/usr/bin/env python3
"""Synthetic self-test of the CSV parsers (build and verify), the end-use
selection rule (both implementations), -0.0 preservation, listing parsing
and every rejection path. Runs in a temporary directory; no network."""
from __future__ import annotations

import array
import math
import random
import struct
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import resstock as R  # noqa: E402
import resstock_verify as V  # noqa: E402

N = 300
MIN_DISTINCT = 50
STATES = ["AA", "BB", "CC", "DD"]


def synth_values(columns: list[dict], rng: random.Random) -> dict:
    """{state: {column: [floats]}} for the end-use columns, designed so the
    rule outcome is known: see EXPECTED below."""
    base_sched = [rng.uniform(5.0, 50.0) for _ in range(N)]
    shifted = base_sched[7:] + base_sched[:7]
    shifted13 = base_sched[13:] + base_sched[:13]
    levels = [rng.uniform(1.0, 9.0) for _ in range(10)]
    data = {}
    for s_pos, st in enumerate(STATES):
        k = 1.0 + 0.37 * s_pos
        cols = {}
        for col in columns:
            if col["kind"] != "end_use":
                continue
            name = col["end_use"] + "." + col["fuel"]
            if name == "vehicle.electricity":  # (a) zero everywhere, signed zeros
                vals = [(-0.0 if t % 3 == 0 else 0.0) for t in range(N)]
            elif name == "heating.propane":  # (a) zero only in DD
                vals = [0.0] * N if st == "DD" else [rng.uniform(0, 100) if t % 2 else 0.0 for t in range(N)]
            elif name == "bath_fan.electricity":  # (b) ten levels
                vals = [levels[rng.randrange(10)] * k for _ in range(N)]
            elif name == "refrigerator.electricity":  # (c) only AA and BB rescaled
                sched = {"AA": base_sched, "BB": base_sched, "CC": shifted, "DD": shifted13}[st]
                vals = [v * k for v in sched]
            elif name == "pv.electricity":  # negative with signed zeros; (a) in CC
                if st == "CC":
                    vals = [-0.0] * N
                else:
                    vals = [(-rng.uniform(0, 300) if 30 < t % 96 < 70 else -0.0) for t in range(N)]
            else:  # genuine: positive with some exact zeros
                vals = [0.0 if rng.random() < 0.1 else rng.uniform(0.0, 1e6) * k for _ in range(N)]
            cols[col["column"]] = vals
        data[st] = cols
    return data


EXPECTED_DROP = {
    "out.electricity.vehicle.energy_consumption": ["a_all_zero"],
    "out.propane.heating.energy_consumption": ["a_all_zero"],
    "out.electricity.bath_fan.energy_consumption": ["b_low_distinct"],
    "out.electricity.refrigerator.energy_consumption": ["c_rescaled_duplicate"],
    "out.electricity.pv.energy_consumption": ["a_all_zero"],
}


def write_csv(path: Path, st: str, columns: list[dict], values: dict, mutate=None) -> None:
    groups, site, fuel_totals = R.total_groups(columns)
    stamps = R.expected_timestamps(N)
    lines = [",".join(R.LEADING + [c["column"] for c in columns])]
    for t in range(N):
        row = [0.0] * len(columns)
        for i, col in enumerate(columns):
            if col["kind"] == "end_use":
                row[i] = values[col["column"]][t]
        for _, ti, members in groups:
            row[ti] = math.fsum(row[j] for j in members)
        row[site] = math.fsum(row[j] for j in fuel_totals)
        fields = [st, R.BUILDING_TYPE, stamps[t], "123", "45678.9"] + [repr(v) for v in row]
        if mutate:
            fields = mutate(t, fields)
            if fields is None:
                continue
        lines.append(",".join(fields))
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def expect_failure(label: str, fn) -> None:
    try:
        fn()
    except (R.RecipeError, V.VerifyError):
        return
    raise AssertionError(f"selftest: {label} was not rejected")


def main() -> int:
    recipe_dir = HERE.parent
    columns = R.load_columns(recipe_dir)
    out_names = [c["column"] for c in columns]
    end_use_offsets = [i for i, c in enumerate(columns) if c["kind"] == "end_use"]
    end_use_names = [out_names[i] for i in end_use_offsets]
    rng = random.Random(20261006)
    data = synth_values(columns, rng)
    stamps = R.expected_timestamps(N)
    if stamps[0] != "2018-01-01 00:15:00" or V.lattice(0) != stamps[0] or V.lattice(N - 1) != stamps[-1]:
        raise AssertionError("timestamp lattices disagree")
    if R.expected_timestamps()[-1] != "2019-01-01 00:00:00" or V.lattice(R.N_ROWS - 1) != "2019-01-01 00:00:00":
        raise AssertionError("full-year lattice does not end at 2019-01-01 00:00:00")

    with tempfile.TemporaryDirectory(prefix="resstock_selftest_") as tmp:
        tmpdir = Path(tmp)
        build_series, verify_series = {}, {}
        keep_offsets = set(end_use_offsets)
        for st in STATES:
            path = tmpdir / f"{st}.csv"
            write_csv(path, st, columns, data[st])
            series, stats = R.parse_state_csv(path, st, columns, stamps)
            if stats["models_used"] != 123 or stats["rows"] != N:
                raise AssertionError("stats mismatch")
            vcols, meta = V.parse_bytes(path.read_bytes(), st, out_names, keep_offsets, end_use_offsets, n_rows=N)
            if meta != ("123", "45678.9"):
                raise AssertionError("verify meta mismatch")
            for off in end_use_offsets:
                name = out_names[off]
                want = struct.pack(f"<{N}d", *data[st][name])
                if series[name].tobytes() != want or struct.pack(f"<{N}d", *vcols[off]) != want:
                    raise AssertionError(f"{st} {name}: decoded bytes differ (signed zeros or values)")
            build_series[st] = series
            verify_series[st] = {out_names[o]: a for o, a in vcols.items()}
        # -0.0 survives bit-exactly
        pv = build_series["AA"]["out.electricity.pv.energy_consumption"]
        if struct.pack("<d", pv[0]) != struct.pack("<d", -0.0):
            raise AssertionError("-0.0 not preserved")

        report = R.select_end_uses(build_series, columns, min_distinct=MIN_DISTINCT)
        vrule = V.evaluate_rule(verify_series, end_use_names, min_distinct=MIN_DISTINCT)
        for name in end_use_names:
            want = EXPECTED_DROP.get(name, [])
            if report[name]["reasons"] != want:
                raise AssertionError(f"build rule {name}: {report[name]['reasons']} != {want}")
            if vrule[name]["flags"] != want or vrule[name]["pairs"] != report[name]["rescaled_pair_count"]:
                raise AssertionError(f"verify rule {name}: {vrule[name]} disagrees")
        ref = report["out.electricity.refrigerator.energy_consumption"]
        if ref["rescaled_pair_count"] != 1 or ref["rescaled_pairs_first"][0]["pair"] != ["AA", "BB"]:
            raise AssertionError(f"rescaled pair detection wrong: {ref}")
        # negative rescaling is still a rescaling
        neg = {"P": {"c": array.array("d", [-2.0 * v for v in range(1, 400)])}, "Q": {"c": array.array("d", [3.0 * v for v in range(1, 400)])}}
        if len(R.rescaled_pairs(neg, "c", ["P", "Q"])) != 1:
            raise AssertionError("negative-ratio rescaling not detected by build")
        vk = {st: V.profile_key(neg[st]["c"]) for st in neg}
        if not V.profiles_match(neg["P"]["c"], neg["Q"]["c"], vk["P"], vk["Q"]):
            raise AssertionError("negative-ratio rescaling not detected by verify")
        near = {"P": {"c": array.array("d", [float(v) for v in range(1, 400)])}, "Q": {"c": array.array("d", [float(v) * (1 + 1e-6 * (v % 2)) for v in range(1, 400)])}}
        vk = {st: V.profile_key(near[st]["c"]) for st in near}
        if R.rescaled_pairs(near, "c", ["P", "Q"]) or V.profiles_match(near["P"]["c"], near["Q"]["c"], vk["P"], vk["Q"]):
            raise AssertionError("a 1e-6 deviation must not count as an exact rescaling")

        # rejection paths
        bad = tmpdir / "bad.csv"
        cases = {
            "NaN cell": lambda t, f: f[:10] + ["nan"] + f[11:] if t == 5 else f,
            "empty cell": lambda t, f: f[:10] + [""] + f[11:] if t == 5 else f,
            "infinite cell": lambda t, f: f[:10] + ["inf"] + f[11:] if t == 5 else f,
            "wrong timestamp": lambda t, f: f[:2] + ["2018-01-01 00:00:00"] + f[3:] if t == 0 else f,
            "wrong state": lambda t, f: ["ZZ"] + f[1:] if t == 9 else f,
            "wrong building type": lambda t, f: f[:1] + ["Mobile Home"] + f[2:] if t == 9 else f,
            "missing last row": lambda t, f: None if t == N - 1 else f,
            "missing middle row": lambda t, f: None if t == 3 else f,
            "extra column": lambda t, f: f + ["1.0"] if t == 7 else f,
            "models_used changes": lambda t, f: f[:3] + ["124"] + f[4:] if t == 100 else f,
        }
        for label, mutate in cases.items():
            write_csv(bad, "AA", columns, data["AA"], mutate)
            expect_failure(f"build parser: {label}", lambda: R.parse_state_csv(bad, "AA", columns, stamps))
            expect_failure(f"verify parser: {label}", lambda: V.parse_bytes(bad.read_bytes(), "AA", out_names, keep_offsets, end_use_offsets, n_rows=N))

        def broken_total(t, f):
            if t == 11:
                idx = 5 + out_names.index("out.natural_gas.total.energy_consumption")
                f = list(f)
                f[idx] = repr(float(f[idx]) + 1.0)
            return f

        write_csv(bad, "AA", columns, data["AA"], broken_total)
        expect_failure("build parser: inconsistent fuel total", lambda: R.parse_state_csv(bad, "AA", columns, stamps))

        def noncanonical(t, f):
            if t == 2:
                idx = 5 + out_names.index("out.electricity.cooling.energy_consumption")
                f = list(f)
                f[idx] = f[idx] + "0" if "e" not in f[idx] else f[idx]
            return f

        write_csv(bad, "AA", columns, data["AA"], noncanonical)
        expect_failure("verify parser: non-canonical token", lambda: V.parse_bytes(bad.read_bytes(), "AA", out_names, keep_offsets, end_use_offsets, n_rows=N))
        write_csv(bad, "AA", columns, data["AA"])
        text = bad.read_text(encoding="ascii").replace("in.state", "in.State", 1)
        bad.write_text(text, encoding="ascii")
        expect_failure("build parser: header", lambda: R.parse_state_csv(bad, "AA", columns, stamps))
        expect_failure("verify parser: header", lambda: V.parse_bytes(bad.read_bytes(), "AA", out_names, keep_offsets, end_use_offsets, n_rows=N))

        # listing parser
        ns = "http://s3.amazonaws.com/doc/2006-03-01/"
        key = R.BY_STATE_PREFIX + "state=AL/al-single-family_detached.csv"
        xml = (f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="{ns}"><IsTruncated>false</IsTruncated>'
               f'<Contents><Key>{key}</Key><LastModified>2021-12-29T21:02:21.000Z</LastModified>'
               f'<ETag>&quot;d6b50a19d737fa114ce92a7bcc009514&quot;</ETag><Size>30462912</Size></Contents></ListBucketResult>')
        listing = tmpdir / "listing.xml"
        listing.write_text(xml, encoding="utf-8")
        entries = R.parse_listing(listing)
        if entries[key] != {"size_bytes": 30462912, "etag_md5": "d6b50a19d737fa114ce92a7bcc009514", "last_modified": "2021-12-29T21:02:21.000Z"}:
            raise AssertionError(f"listing parse wrong: {entries}")
        listing.write_text(xml.replace("<IsTruncated>false", "<IsTruncated>true"), encoding="utf-8")
        expect_failure("truncated listing", lambda: R.parse_listing(listing))
        if R.object_url(key) != R.BUCKET_URL + "/" + key.replace("state=AL", "state%3DAL"):
            raise AssertionError("object URL encoding wrong")
    print("selftest: OK (parsers agree bit-exactly incl. -0.0; rule a/b/c outcomes match in both implementations; 13 rejection paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
