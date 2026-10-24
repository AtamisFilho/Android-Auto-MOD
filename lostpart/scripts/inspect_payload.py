"""Inspect the payload of the Linux build (development helper)."""

from __future__ import annotations

import io
import re
import struct
import tarfile
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "dist" / "lostpart-linux-x64"

PAYLOAD_MAGIC = b"LOSTPART_PAYLOAD_V1\n"
TRAILER_MAGIC = b"LOSTPART_END_V1\n"
TRAILER_SIZE = 8 + 8 + len(PAYLOAD_MAGIC) + len(TRAILER_MAGIC)


def main() -> None:
    data = PATH.read_bytes()
    trailer = data[-TRAILER_SIZE:]
    offset, size = struct.unpack("<QQ", trailer[:16])
    print(f"file={len(data)} offset={offset} size={size}")
    assert offset + size == len(data) - TRAILER_SIZE

    payload = data[offset:offset + size]
    tar = tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz")
    members = tar.getmembers()
    names = {member.name for member in members}
    print(f"total members: {len(members)}")

    print("--- python/bin ---")
    for member in members:
        if member.name.startswith("python/bin/"):
            kind = "link->" + member.linkname if member.issym() else "file"
            print(f"   {member.name}  mode={member.mode:o} {kind}")

    print("--- python/lib top level ---")
    for name in sorted(names):
        if re.fullmatch(r"python/lib/[^/]+/?", name):
            print(f"   {name}")

    print("--- stdlib presence ---")
    for want in (
        "python/lib/python3.13/os.py",
        "python/lib/python3.13/encodings/__init__.py",
        "python/lib/python3.13/sqlite3/__init__.py",
        "python/lib/python3.13/ctypes/__init__.py",
    ):
        print(f"   {want} -> {want in names}")

    print("--- app ---")
    for name in sorted(names):
        if name.startswith("app/") and name.count("/") <= 2:
            print(f"   {name}")


if __name__ == "__main__":
    main()
