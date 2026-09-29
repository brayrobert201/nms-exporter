"""Decode a No Man's Sky save (.hg) into a dict. Standard library only.

A save is a chain of chunks, each `<u32 magic 0xFEEDA1E5><u32 comp><u32 uncomp>
<u32 0>` followed by a raw LZ4 *block* (not an LZ4 frame). The JSON inside uses
obfuscated three-character keys; `demap()` translates them with MBINCompiler's
mapping.json.
"""
from __future__ import annotations

import json
import struct

MAGIC = 0xFEEDA1E5
MAPPING_URL = "https://github.com/monkeyman192/MBINCompiler/releases/latest/download/mapping.json"


def lz4_block_decompress(src: bytes, usz: int = 0) -> bytes:
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        tok = src[i]
        i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        dst += src[i:i + lit]
        i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        ml = tok & 0xF
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(dst) - off
        if off >= ml:                      # no overlap: one slice copy
            dst += dst[start:start + ml]
        else:                              # overlapping run: byte by byte
            for k in range(ml):
                dst.append(dst[start + k])
    return bytes(dst)


def decode_bytes(data: bytes) -> bytes:
    out, i = b"", 0
    while i < len(data):
        magic, csz, usz, _ = struct.unpack_from("<IIII", data, i)
        i += 16
        if magic != MAGIC:
            raise ValueError(f"bad chunk magic {magic:#x} at offset {i - 16}")
        out += lz4_block_decompress(data[i:i + csz], usz)
        i += csz
    return out.rstrip(b"\0")


def load_mapping(path: str) -> dict:
    with open(path) as fh:
        return {e["Key"]: e["Value"] for e in json.load(fh)["Mapping"]}


def demap(o, m: dict):
    if isinstance(o, dict):
        return {m.get(k, k): demap(v, m) for k, v in o.items()}
    if isinstance(o, list):
        return [demap(x, m) for x in o]
    return o


def decode_save(path: str, mapping: dict | None = None) -> dict:
    """Return the save as a dict; mapping=None keeps the obfuscated keys."""
    with open(path, "rb") as fh:
        raw = decode_bytes(fh.read())
    # a few item ids contain non-UTF-8 bytes; replace rather than fail
    j = json.loads(raw.decode("utf8", "replace"))
    return demap(j, mapping) if mapping else j
