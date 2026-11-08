"""
savefile_codec.py — F1 Manager 2024 .sav unpack/repack (pure-Python)

Attribution: Derived from IUrreta/DatabaseEditor (GPL-3.0); .sav layout
repacker credited to xAranaktu. This Python derivative is also GPL-3.0.
See README.md for the full attribution discussion.

This codec treats the GVAS UE5 metadata section as opaque bytes and
locates the post-GVAS anchor by scanning for the unique pattern:
  [int32 unk_zero=0][int32 total_size][int32 s1][int32 s2][int32 s3]
  [zlib data starting with 0x78][optional trailing zero padding]
with all of: file-size math closing, zlib magic, and only zeros past
the blob. Trailing zero padding (some saves have ~700+ bytes from
game-side buffer over-allocation) is preserved across round-trips.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import struct
import sys
import tempfile
import zlib
from dataclasses import dataclass


ZLIB_MAGIC_FIRST_BYTE = 0x78
ANCHOR_TRAILER_LEN = 20


@dataclass
class Unpacked:
    header: bytes
    main_db: bytes
    db2: bytes
    db3: bytes
    total_size: int
    s1: int
    s2: int
    s3: int
    trailing_padding: int = 0


def _find_anchor(data: bytes) -> int:
    fs = len(data)
    candidates: list[int] = []
    for H in range(64, fs - ANCHOR_TRAILER_LEN):
        if data[H] | data[H + 1] | data[H + 2] | data[H + 3]:
            continue
        total_size = struct.unpack_from("<i", data, H + 4)[0]
        if total_size <= 0:
            continue
        blob_end = H + ANCHOR_TRAILER_LEN + total_size
        if blob_end > fs:
            continue
        if data[H + ANCHOR_TRAILER_LEN] != ZLIB_MAGIC_FIRST_BYTE:
            continue
        if any(data[blob_end:fs]):
            continue
        candidates.append(H)
        if len(candidates) > 1:
            break
    if not candidates:
        raise ValueError(
            "Could not locate save-file anchor. Not a recognized F1M24 "
            ".sav, corrupted, or an unsupported layout."
        )
    if len(candidates) > 1:
        raise ValueError(
            f"Ambiguous save structure: multiple anchors at {candidates}."
        )
    return candidates[0]


def unpack_bytes(data: bytes) -> Unpacked:
    if data[:4] != b"GVAS":
        raise ValueError("Not a GVAS save file (missing 'GVAS' magic).")
    H = _find_anchor(data)
    total_size, s1, s2, s3 = struct.unpack_from("<iiii", data, H + 4)
    header = bytes(data[:H])
    blob = data[H + ANCHOR_TRAILER_LEN : H + ANCHOR_TRAILER_LEN + total_size]
    decompressed = zlib.decompress(blob)
    expected = s1 + s2 + s3
    if len(decompressed) != expected:
        raise ValueError(
            f"Decompressed size {len(decompressed)} != s1+s2+s3 = {expected}."
        )
    main_db = decompressed[:s1]
    db2 = decompressed[s1 : s1 + s2]
    db3 = decompressed[s1 + s2 : s1 + s2 + s3]
    if s1 > 0 and main_db[:16] != b"SQLite format 3\x00":
        raise ValueError("Main chunk is not a SQLite database.")
    trailing_padding = len(data) - (H + ANCHOR_TRAILER_LEN + total_size)
    return Unpacked(
        header=header, main_db=main_db, db2=db2, db3=db3,
        total_size=total_size, s1=s1, s2=s2, s3=s3,
        trailing_padding=trailing_padding,
    )


def repack_bytes(header: bytes, main_db: bytes, db2: bytes, db3: bytes,
                 trailing_padding: int = 0) -> bytes:
    if header[:4] != b"GVAS":
        raise ValueError("Header bytes do not start with 'GVAS'.")
    if trailing_padding < 0:
        raise ValueError("trailing_padding must be >= 0")
    s1, s2, s3 = len(main_db), len(db2), len(db3)
    payload = main_db + db2 + db3
    compressed = zlib.compress(payload, level=9)
    trailer = struct.pack("<iiiii", 0, len(compressed), s1, s2, s3)
    result = header + trailer + compressed
    if trailing_padding:
        result += b"\x00" * trailing_padding
    return result


def unpack_file(sav_path: pathlib.Path, out_dir: pathlib.Path) -> Unpacked:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = sav_path.read_bytes()
    u = unpack_bytes(raw)
    (out_dir / "header.bin").write_bytes(u.header)
    (out_dir / "main.db").write_bytes(u.main_db)
    (out_dir / "db2.bin").write_bytes(u.db2)
    (out_dir / "db3.bin").write_bytes(u.db3)
    (out_dir / "sizes.json").write_text(json.dumps({
        "header_size": len(u.header),
        "compressed_size": u.total_size,
        "main_db_size": u.s1,
        "db2_size": u.s2,
        "db3_size": u.s3,
        "trailing_padding": u.trailing_padding,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_filename": sav_path.name,
    }, indent=2))
    return u


def _read_or_empty(p: pathlib.Path) -> bytes:
    return p.read_bytes() if p.exists() else b""


def repack_file(in_dir: pathlib.Path, out_sav: pathlib.Path,
                verify: bool = True) -> None:
    header = (in_dir / "header.bin").read_bytes()
    main_db = (in_dir / "main.db").read_bytes()
    db2 = _read_or_empty(in_dir / "db2.bin")
    db3 = _read_or_empty(in_dir / "db3.bin")
    trailing_padding = 0
    sp = in_dir / "sizes.json"
    if sp.exists():
        try:
            trailing_padding = int(json.loads(sp.read_text()).get("trailing_padding", 0))
        except Exception:
            trailing_padding = 0
    out_bytes = repack_bytes(header, main_db, db2, db3, trailing_padding=trailing_padding)
    out_sav.parent.mkdir(parents=True, exist_ok=True)
    out_sav.write_bytes(out_bytes)
    if verify:
        v = unpack_bytes(out_sav.read_bytes())
        if v.header != header:
            raise RuntimeError("Repack verify failed: header mismatch.")
        if v.main_db != main_db:
            raise RuntimeError("Repack verify failed: main_db mismatch.")
        if v.db2 != db2:
            raise RuntimeError("Repack verify failed: db2 mismatch.")
        if v.db3 != db3:
            raise RuntimeError("Repack verify failed: db3 mismatch.")
        if v.trailing_padding != trailing_padding:
            raise RuntimeError(
                f"Repack verify failed: trailing_padding {v.trailing_padding} != {trailing_padding}"
            )


def roundtrip(in_sav: pathlib.Path, out_sav: pathlib.Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        td_p = pathlib.Path(td)
        unpack_file(in_sav, td_p)
        repack_file(td_p, out_sav, verify=True)


def _usage() -> str:
    return (
        "Usage:\n"
        "  python savefile_codec.py unpack <input.sav> <out_dir>\n"
        "  python savefile_codec.py repack <in_dir> <output.sav>\n"
        "  python savefile_codec.py roundtrip <input.sav> <output.sav>\n"
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write(_usage())
        return 2
    cmd = argv[1]
    try:
        if cmd == "unpack" and len(argv) == 4:
            u = unpack_file(pathlib.Path(argv[2]), pathlib.Path(argv[3]))
            print(f"unpacked: header={len(u.header)}B  main={u.s1}B  "
                  f"db2={u.s2}B  db3={u.s3}B  compressed={u.total_size}B  "
                  f"trailing_padding={u.trailing_padding}B")
            return 0
        if cmd == "repack" and len(argv) == 4:
            repack_file(pathlib.Path(argv[2]), pathlib.Path(argv[3]))
            print(f"repacked + verified: {argv[3]}")
            return 0
        if cmd == "roundtrip" and len(argv) == 4:
            roundtrip(pathlib.Path(argv[2]), pathlib.Path(argv[3]))
            print(f"round-trip ok: {argv[3]}")
            return 0
    except Exception as e:
        sys.stderr.write(f"ERROR: {type(e).__name__}: {e}\n")
        return 1
    sys.stderr.write(_usage())
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
