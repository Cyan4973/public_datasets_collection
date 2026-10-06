#!/usr/bin/env python3
"""Self-test of the inert torch-zip reader on a synthetic checkpoint.

Builds, without torch, a protocol-2 pickle that references the same globals a
real MACE checkpoint does (mace.* module classes, torch._utils rebuild
functions, torch.DoubleStorage persistent ids, a ParameterList), stores it in
a STORED zip written through an unseekable stream (so members carry data
descriptors, like torch's writer), and checks names, offsets, strides, both
member readers, statistics, the near-duplicate screen and global rejection.
"""
from __future__ import annotations

import collections
import io
import pickle
import struct
import sys
import tempfile
import types
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mace_weights as mw  # noqa: E402
import torch_zip_pickle as tzp  # noqa: E402


def fake_module(name: str) -> types.ModuleType:
    parts = name.split(".")
    for depth in range(1, len(parts) + 1):
        dotted = ".".join(parts[:depth])
        if dotted not in sys.modules:
            sys.modules[dotted] = types.ModuleType(dotted)
            if depth > 1:
                setattr(sys.modules[".".join(parts[:depth - 1])], parts[depth - 1], sys.modules[dotted])
    return sys.modules[name]


def install_fakes():
    torch = fake_module("torch")
    utils = fake_module("torch._utils")
    container = fake_module("torch.nn.modules.container")
    models = fake_module("mace.modules.models")
    blocks = fake_module("mace.modules.blocks")

    class DoubleStorage:
        pass

    class LongStorage:
        pass

    for cls in (DoubleStorage, LongStorage):
        cls.__module__ = "torch"
        cls.__qualname__ = cls.__name__
    torch.DoubleStorage = DoubleStorage
    torch.LongStorage = LongStorage

    def _rebuild_tensor_v2(*args):  # never executed by the reader
        raise AssertionError

    def _rebuild_parameter(*args):  # never executed by the reader
        raise AssertionError

    for fn in (_rebuild_tensor_v2, _rebuild_parameter):
        fn.__module__ = "torch._utils"
        fn.__qualname__ = fn.__name__
        setattr(utils, fn.__name__, fn)

    class FakeStorage:
        def __init__(self, kind, key, values):
            self.kind, self.key, self.values = kind, key, values

    class FakeTensor:
        def __init__(self, storage, offset, size, stride):
            self.args = (storage, offset, size, stride, False, collections.OrderedDict())

        def __reduce__(self):
            return (utils._rebuild_tensor_v2, self.args)

    class FakeParameter:
        def __init__(self, tensor):
            self.tensor = tensor

        def __reduce__(self):
            return (utils._rebuild_parameter, (self.tensor, True, collections.OrderedDict()))

    def module_class(module, name):
        cls = type(name, (), {})
        cls.__module__ = module.__name__
        cls.__qualname__ = name
        setattr(module, name, cls)
        return cls

    classes = {
        "ScaleShiftMACE": module_class(models, "ScaleShiftMACE"),
        "Block": module_class(blocks, "RealAgnosticInteractionBlock"),
        "ParameterList": module_class(container, "ParameterList"),
        "ModuleList": module_class(container, "ModuleList"),
    }
    return torch, FakeStorage, FakeTensor, FakeParameter, classes


def make_module(cls, parameters=None, buffers=None, modules=None):
    obj = cls.__new__(cls)
    obj.__dict__.update({
        "training": False,
        "_parameters": collections.OrderedDict(parameters or {}),
        "_buffers": collections.OrderedDict(buffers or {}),
        "_modules": collections.OrderedDict(modules or {}),
    })
    return obj


def main() -> None:
    torch, FakeStorage, FakeTensor, FakeParameter, classes = install_fakes()
    s0 = FakeStorage("double", "0", [float(i) * 0.37 - 1.0 for i in range(1200)])
    s1 = FakeStorage("double", "1", [1e-316 * (i + 1) for i in range(10)] + [0.5 + i for i in range(2000)])
    s2 = FakeStorage("double", "2", [(-1) ** i * (i / 7.0) for i in range(1500)])
    s3 = FakeStorage("double", "3", [float(i) for i in range(64)])
    s4 = FakeStorage("long", "4", list(range(5)))
    storages = [s0, s1, s2, s3, s4]

    w_skip = FakeParameter(FakeTensor(s0, 0, (1200,), (1,)))
    w_view = FakeParameter(FakeTensor(s1, 10, (40, 50), (50, 1)))  # offset view into storage 1
    w_pl0 = FakeParameter(FakeTensor(s2, 0, (3, 500), (500, 1)))
    w_small = FakeParameter(FakeTensor(s3, 0, (8, 8), (8, 1)))
    buf = FakeTensor(s4, 0, (5,), (1,))
    plist = make_module(classes["ParameterList"], parameters={"0": w_pl0, "1": None})
    block = make_module(classes["Block"], parameters={"weight": w_skip}, modules={"weights": plist})
    blocks = make_module(classes["ModuleList"], modules={"0": block})
    root = make_module(
        classes["ScaleShiftMACE"],
        parameters={"view": w_view, "small": w_small},
        buffers={"atomic_numbers": buf},
        modules={"interactions": blocks},
    )

    class Writer(pickle.Pickler):
        def persistent_id(self, obj):
            if isinstance(obj, FakeStorage):
                kind = torch.DoubleStorage if obj.kind == "double" else torch.LongStorage
                return ("storage", kind, obj.key, "cpu", len(obj.values))
            return None

    buffer = io.BytesIO()
    Writer(buffer, protocol=2).dump(root)
    pkl = buffer.getvalue()

    tree = tzp.load_module_tree(pkl)
    assert tree["root_class"] == "mace.modules.models.ScaleShiftMACE", tree["root_class"]
    names = {name: t for name, t in tree["parameters"]}
    assert list(names) == ["view", "small", "interactions.0.weight", "interactions.0.weights.0"], list(names)
    assert [n for n, _ in tree["buffers"]] == ["atomic_numbers"]
    assert tree["buffers"][0][1].storage.dtype == "int64"
    view = names["view"]
    assert view.offset == 10 and view.size == (40, 50) and view.byte_range() == (80, 80 + 2000 * 8)
    assert view.is_c_contiguous()
    assert not tzp.TensorRef(view.storage, 0, (40, 50), (1, 40)).is_c_contiguous()
    assert tzp.TensorRef(view.storage, 0, (1, 50), (999, 1)).is_c_contiguous()

    # Disallowed globals must raise instead of resolving.
    evil = b"\x80\x02cos\nsystem\nq\x00X\x04\x00\x00\x00trueq\x01\x85q\x02Rq\x03."
    try:
        tzp.load_module_tree(evil)
    except pickle.UnpicklingError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("os.system global was not rejected")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "synthetic.model"

        class Unseekable:
            def __init__(self, fh):
                self.fh = fh

            def write(self, data):
                return self.fh.write(data)

            def flush(self):
                self.fh.flush()

        with path.open("wb") as raw, zipfile.ZipFile(Unseekable(raw), "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("synthetic-run/data.pkl", pkl)
            archive.writestr("synthetic-run/byteorder", b"little")
            for storage in storages:
                fmt = "<%dd" % len(storage.values) if storage.kind == "double" else "<%dq" % len(storage.values)
                archive.writestr(f"synthetic-run/data/{storage.key}", struct.pack(fmt, *storage.values))
            archive.writestr("synthetic-run/version", b"3\n")

        with path.open("rb") as handle:
            directory = tzp.read_central_directory(handle, path.stat().st_size)
            members = directory["members"]
            assert directory["count"] == 8
            assert all(m["flags"] & 0x08 for m in members.values()), "expected data descriptors"
            raw_view = tzp.read_stored_member(handle, members["synthetic-run/data/1"])
        with zipfile.ZipFile(path) as archive:
            assert archive.read("synthetic-run/data/1") == raw_view
            assert archive.read("synthetic-run/data.pkl") == pkl
        start, end = view.byte_range()
        payload = raw_view[start:end]
        values = struct.unpack("<2000d", payload)
        assert values[0] == 0.5 and values[-1] == 1999.5, (values[0], values[-1])

    stats = mw.tensor_stats(struct.pack("<6d", 0.0, 1e-310, 0.1, 0.5, -2.0, 3.25))
    assert stats["zero_count"] == 1 and stats["subnormal_count"] == 1, stats
    assert stats["f32_exact_count"] == 4, stats  # 0.0, 0.5, -2.0, 3.25
    assert stats["minimum"] == -2.0 and stats["maximum"] == 3.25
    try:
        mw.tensor_stats(struct.pack("<2d", 1.0, float("nan")))
    except ValueError:
        pass
    else:
        raise AssertionError("NaN was not rejected")

    a = [0.1 * i + 0.05 for i in range(100)]
    b = [x * (1 + 1e-9) for x in a]
    c = [x + 1.0 for x in a]
    excluded, pairs = mw.near_duplicate_screen([
        {"key": "A", "ck_index": 0, "name": "w", "shape": [100], "probe": a},
        {"key": "B", "ck_index": 1, "name": "w", "shape": [100], "probe": b},
        {"key": "C", "ck_index": 2, "name": "w", "shape": [100], "probe": c},
        {"key": "D", "ck_index": 3, "name": "w", "shape": [10, 10], "probe": a},
    ])
    assert excluded == ["B"], excluded
    assert len(pairs) == 2 and pairs[0]["match_fraction"] == 1.0 and pairs[1]["match_fraction"] == 0.0, pairs
    assert len(mw.probe_positions(5_832_704)) <= mw.NEAR_DUP_POSITIONS
    print("selftest ok: inert unpickler names/offsets/strides, data-descriptor zip readers, stats, near-dup screen")


if __name__ == "__main__":
    main()
