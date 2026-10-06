#!/usr/bin/env python3
"""Inert reader for legacy PyTorch zip checkpoints (torch.save of a whole module).

Pure standard library. torch, mace and e3nn are never imported and no pickle
code runs beyond an explicit whitelist:

* collections.OrderedDict, builtins.set and _codecs.encode are the only real
  callables the pickle may invoke;
* torch._utils._rebuild_tensor_v2 and torch._utils._rebuild_parameter are
  replaced by recorders of (storage key, offset, size, stride);
* torch.DoubleStorage / FloatStorage / LongStorage become dtype markers that
  persistent_load turns into StorageRef records;
* every other mace.*, e3nn.* or torch.* global becomes an inert stub class
  that only stores its constructor arguments and pickled state;
* anything else raises.

The module tree is then walked through the stubs' pickled ``__dict__`` state
(``_modules`` / ``_parameters`` / ``_buffers``) to name every tensor.

The file also contains a small raw ZIP central-directory parser so a verifier
can slice member payloads directly by local-header offset, independently of
the ``zipfile`` module.
"""
from __future__ import annotations

import _codecs
import collections
import io
import math
import pickle
import struct

ALLOWED_GLOBALS = {
    ("collections", "OrderedDict"): collections.OrderedDict,
    ("builtins", "set"): set,
    ("__builtin__", "set"): set,
    ("_codecs", "encode"): _codecs.encode,
}
STORAGE_TYPES = {
    "DoubleStorage": ("float64", 8),
    "FloatStorage": ("float32", 4),
    "LongStorage": ("int64", 8),
}
STUB_ROOTS = ("mace", "e3nn", "torch")


class Stub:
    """Inert stand-in for any whitelisted-by-prefix class or function."""

    _qualname = "?"

    def __new__(cls, *args, **kwargs):
        obj = object.__new__(cls)
        obj.__dict__["_stub_args"] = args
        obj.__dict__["_stub_state"] = None
        obj.__dict__["_stub_items"] = []
        obj.__dict__["_stub_dictitems"] = {}
        return obj

    def __init__(self, *args, **kwargs):
        pass

    def __setstate__(self, state):
        self.__dict__["_stub_state"] = state

    def append(self, item):
        self.__dict__["_stub_items"].append(item)

    def extend(self, items):
        self.__dict__["_stub_items"].extend(items)

    def __setitem__(self, key, value):
        self.__dict__["_stub_dictitems"][key] = value

    def __repr__(self):
        return f"<inert stub {self._qualname}>"


class StorageType:
    def __init__(self, name: str):
        self.name = name
        self.dtype, self.itemsize = STORAGE_TYPES[name]


class StorageRef:
    def __init__(self, storage_type: StorageType, key: str, location: str, numel: int):
        self.type_name = storage_type.name
        self.dtype = storage_type.dtype
        self.itemsize = storage_type.itemsize
        self.key = key
        self.location = location
        self.numel = numel


class TensorRef:
    def __init__(self, storage: StorageRef, offset: int, size: tuple[int, ...], stride: tuple[int, ...]):
        self.storage = storage
        self.offset = offset
        self.size = size
        self.stride = stride
        self.parameter = False

    @property
    def numel(self) -> int:
        return math.prod(self.size)

    def is_c_contiguous(self) -> bool:
        expected = 1
        for dim, step in zip(reversed(self.size), reversed(self.stride)):
            if dim != 1 and step != expected:
                return False
            expected *= dim
        return True

    def byte_range(self) -> tuple[int, int]:
        start = self.offset * self.storage.itemsize
        return start, start + self.numel * self.storage.itemsize


class ParameterRef:
    def __init__(self, data: TensorRef):
        self.data = data
        data.parameter = True


def _int_tuple(value, label: str) -> tuple[int, ...]:
    if not isinstance(value, tuple) or not all(isinstance(v, int) and v >= 0 for v in value):
        raise pickle.UnpicklingError(f"{label} must be a tuple of non-negative ints: {value!r}")
    return value


class InertUnpickler(pickle.Unpickler):
    def __init__(self, handle):
        super().__init__(handle)
        self.stub_classes: dict[str, type] = {}
        self.storages: dict[str, StorageRef] = {}
        self.tensors: list[TensorRef] = []
        self.parameters: list[ParameterRef] = []

    def find_class(self, module, name):
        key = (module, name)
        if key in ALLOWED_GLOBALS:
            return ALLOWED_GLOBALS[key]
        if module == "torch" and name in STORAGE_TYPES:
            return StorageType(name)
        if key == ("torch._utils", "_rebuild_tensor_v2"):
            return self._rebuild_tensor_v2
        if key == ("torch._utils", "_rebuild_parameter"):
            return self._rebuild_parameter
        if module.split(".")[0] in STUB_ROOTS:
            qualname = f"{module}.{name}"
            if qualname not in self.stub_classes:
                self.stub_classes[qualname] = type(name, (Stub,), {"_qualname": qualname})
            return self.stub_classes[qualname]
        raise pickle.UnpicklingError(f"global not allowed: {module}.{name}")

    def persistent_load(self, pid):
        if not (
            isinstance(pid, tuple)
            and len(pid) == 5
            and pid[0] == "storage"
            and isinstance(pid[1], StorageType)
            and isinstance(pid[2], str)
            and isinstance(pid[3], str)
            and isinstance(pid[4], int)
        ):
            raise pickle.UnpicklingError(f"unexpected persistent id: {pid!r}")
        _, storage_type, key, location, numel = pid
        ref = self.storages.get(key)
        if ref is None:
            ref = StorageRef(storage_type, key, location, numel)
            self.storages[key] = ref
        elif ref.type_name != storage_type.name or ref.numel != numel:
            raise pickle.UnpicklingError(f"conflicting declarations for storage {key}")
        return ref

    def _rebuild_tensor_v2(self, storage, storage_offset, size, stride, requires_grad, backward_hooks, metadata=None):
        if not isinstance(storage, StorageRef) or not isinstance(storage_offset, int) or storage_offset < 0:
            raise pickle.UnpicklingError("tensor rebuild without a valid storage/offset")
        tensor = TensorRef(storage, storage_offset, _int_tuple(size, "size"), _int_tuple(stride, "stride"))
        if len(tensor.size) != len(tensor.stride):
            raise pickle.UnpicklingError("tensor size/stride rank mismatch")
        self.tensors.append(tensor)
        return tensor

    def _rebuild_parameter(self, data, requires_grad, backward_hooks):
        if not isinstance(data, TensorRef):
            raise pickle.UnpicklingError("parameter rebuild without a tensor")
        ref = ParameterRef(data)
        self.parameters.append(ref)
        return ref


def _walk(module, prefix: str, parameters: list, buffers: list, seen: set) -> None:
    if not isinstance(module, Stub) or id(module) in seen:
        return
    seen.add(id(module))
    state = module._stub_state
    if not isinstance(state, dict):
        return
    for name, value in (state.get("_parameters") or {}).items():
        if value is None:
            continue
        if not isinstance(value, ParameterRef):
            raise ValueError(f"non-parameter object in _parameters: {prefix}{name}")
        parameters.append((prefix + name, value.data))
    for name, value in (state.get("_buffers") or {}).items():
        if value is None:
            continue
        if not isinstance(value, TensorRef):
            raise ValueError(f"non-tensor object in _buffers: {prefix}{name}")
        buffers.append((prefix + name, value))
    for name, child in (state.get("_modules") or {}).items():
        if child is not None:
            _walk(child, prefix + name + ".", parameters, buffers, seen)


def load_module_tree(pickle_bytes: bytes) -> dict:
    """Decode a torch-saved module inertly and name every tensor.

    Returns a dict with the root class name, the named parameters and buffers
    (lists of (name, TensorRef)), all storages, and the stub class names seen.
    Raises if any rebuilt tensor is not reachable by name, if a parameter is
    named twice, or if two tensors share a storage.
    """
    unpickler = InertUnpickler(io.BytesIO(pickle_bytes))
    root = unpickler.load()
    if not isinstance(root, Stub):
        raise ValueError("checkpoint root is not a module object")
    parameters: list[tuple[str, TensorRef]] = []
    buffers: list[tuple[str, TensorRef]] = []
    _walk(root, "", parameters, buffers, set())
    named = [id(t) for _, t in parameters] + [id(t) for _, t in buffers]
    if len(named) != len(set(named)):
        raise ValueError("a tensor is reachable under two names")
    if set(named) != {id(t) for t in unpickler.tensors}:
        raise ValueError("some rebuilt tensors are not reachable as named parameters/buffers")
    if len(parameters) != len(unpickler.parameters):
        raise ValueError("some rebuilt parameters are not reachable by name")
    keys = [t.storage.key for t in unpickler.tensors]
    if len(keys) != len(set(keys)):
        raise ValueError("tensors share a storage")
    if len({name for name, _ in parameters}) != len(parameters):
        raise ValueError("duplicate parameter names")
    return {
        "root_class": root._qualname,
        "parameters": parameters,
        "buffers": buffers,
        "storages": unpickler.storages,
        "stub_classes": sorted(unpickler.stub_classes),
    }


# --- raw ZIP access (independent of the zipfile module) ---------------------

def read_central_directory(handle, file_size: int) -> dict:
    """Parse EOCD (+ZIP64) and the central directory; return members by name."""
    tail_len = min(file_size, 65536 + 22 + 56 + 20)
    handle.seek(file_size - tail_len)
    tail = handle.read(tail_len)
    eocd_at = tail.rfind(b"PK\x05\x06")
    if eocd_at < 0:
        raise ValueError("ZIP end-of-central-directory record not found")
    (_, _, _, _, count, cd_size, cd_offset, _) = struct.unpack("<IHHHHIIH", tail[eocd_at:eocd_at + 22])
    z64_at = tail.rfind(b"PK\x06\x06", 0, eocd_at)
    if z64_at >= 0:
        (_, _, _, _, _, _, _, count, cd_size, cd_offset) = struct.unpack("<IQHHIIQQQQ", tail[z64_at:z64_at + 56])
    handle.seek(cd_offset)
    cd = handle.read(cd_size)
    if len(cd) != cd_size:
        raise ValueError("truncated ZIP central directory")
    members: dict[str, dict] = {}
    pos = 0
    for _ in range(count):
        fields = struct.unpack("<IHHHHHHIIIHHHHHII", cd[pos:pos + 46])
        (sig, _, _, flags, method, _, _, crc, csize, usize, name_len, extra_len, comment_len, _, _, _, local_offset) = fields
        if sig != 0x02014B50:
            raise ValueError("bad ZIP central-directory signature")
        name = cd[pos + 46:pos + 46 + name_len].decode("utf-8")
        extra = cd[pos + 46 + name_len:pos + 46 + name_len + extra_len]
        q = 0
        while q + 4 <= len(extra):
            header_id, header_len = struct.unpack("<HH", extra[q:q + 4])
            if header_id == 1:
                values = list(struct.unpack("<" + "Q" * (header_len // 8), extra[q + 4:q + 4 + header_len]))
                if usize == 0xFFFFFFFF:
                    usize = values.pop(0)
                if csize == 0xFFFFFFFF:
                    csize = values.pop(0)
                if local_offset == 0xFFFFFFFF:
                    local_offset = values.pop(0)
            q += 4 + header_len
        if name in members:
            raise ValueError(f"duplicate ZIP member {name}")
        members[name] = {
            "name": name,
            "flags": flags,
            "method": method,
            "crc32": crc,
            "compressed_size": csize,
            "size": usize,
            "local_header_offset": local_offset,
        }
        pos += 46 + name_len + extra_len + comment_len
    return {"count": count, "cd_offset": cd_offset, "cd_size": cd_size, "members": members}


def member_data_offset(handle, member: dict) -> int:
    handle.seek(member["local_header_offset"])
    header = handle.read(30)
    sig, _, _, method, _, _, _, _, _, name_len, extra_len = struct.unpack("<IHHHHHIIIHH", header)
    if sig != 0x04034B50 or method != member["method"]:
        raise ValueError(f"bad local header for {member['name']}")
    name = handle.read(name_len).decode("utf-8")
    if name != member["name"]:
        raise ValueError(f"local header name mismatch for {member['name']}")
    return member["local_header_offset"] + 30 + name_len + extra_len


def read_stored_member(handle, member: dict) -> bytes:
    if member["method"] != 0 or member["compressed_size"] != member["size"]:
        raise ValueError(f"member is not STORED: {member['name']}")
    handle.seek(member_data_offset(handle, member))
    data = handle.read(member["size"])
    if len(data) != member["size"]:
        raise ValueError(f"truncated member {member['name']}")
    return data
