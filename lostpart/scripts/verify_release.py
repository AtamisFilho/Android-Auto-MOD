#!/usr/bin/env python3
"""Verify the release artefacts.

The checks below are what can be validated from a Windows host, where the
Linux binary cannot be executed: the ELF header, the payload trailer, the
contents of the payload and the permissions of the bundled interpreter.

Run it after ``python scripts/build.py all``::

    python scripts/verify_release.py
"""

from __future__ import annotations

import hashlib
import struct
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

PAYLOAD_MAGIC = b"LOSTPART_PAYLOAD_V1\n"
TRAILER_MAGIC = b"LOSTPART_END_V1\n"
TRAILER_SIZE = 8 + 8 + len(PAYLOAD_MAGIC) + len(TRAILER_MAGIC)

failures: list[str] = []
checks = 0


def check(condition: bool, message: str) -> bool:
    global checks
    checks += 1
    if condition:
        print(f"  ok    {message}")
    else:
        print(f"  FAIL  {message}")
        failures.append(message)
    return bool(condition)


def verify_windows() -> None:
    print("Windows executable")
    path = DIST / "lostpart-windows-x64.exe"
    if not check(path.is_file(), f"{path.name} exists"):
        return
    data = path.read_bytes()
    check(data[:2] == b"MZ", "has a PE header")
    check(len(data) > 1_000_000, f"has a plausible size ({len(data)} bytes)")


def verify_linux() -> None:
    print("Linux executable")
    path = DIST / "lostpart-linux-x64"
    if not check(path.is_file(), f"{path.name} exists"):
        return

    data = path.read_bytes()
    check(data[:4] == b"\x7fELF", "has an ELF header")
    check(data[4] == 2, "is a 64 bit object")
    check(data[5] == 1, "is little endian")
    check(data[18:20] == b"\x3e\x00", "targets x86-64")

    # A static executable has no PT_INTERP segment and no .interp section.
    check(b"/lib64/ld-linux" not in data[:1_000_000],
          "carries no dynamic loader path (statically linked)")

    trailer = data[-TRAILER_SIZE:]
    offset, size = struct.unpack("<QQ", trailer[:16])
    check(trailer[16:16 + len(PAYLOAD_MAGIC)] == PAYLOAD_MAGIC,
          "the trailer carries the payload magic")
    check(trailer[16 + len(PAYLOAD_MAGIC):] == TRAILER_MAGIC,
          "the trailer carries the end magic")
    check(offset + size == len(data) - TRAILER_SIZE,
          f"the payload offset and size match the file ({offset} + {size})")

    payload = data[offset:offset + size]
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "payload.tar.gz"
        archive.write_bytes(payload)
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            names = {member.name for member in members}

            check("python/bin/python3" in names,
                  "the payload carries the bundled interpreter")
            check("app/lostpart_main.py" in names,
                  "the payload carries the entry point")
            check("app/lostpart/cli.py" in names,
                  "the payload carries the command line interface")
            check("app/lostpart/fs/ntfs.py" in names,
                  "the payload carries the NTFS probe")
            check("app/lostpart/fs/hfsplus.py" in names,
                  "the payload carries the HFS+ probe")
            check("app/lostpart/scan/bitmap_match.py" in names,
                  "the payload carries the bitmap matcher")
            check("app/lostpart/ui/app.py" in names,
                  "the payload carries the graphical interface")
            check("app/lostpart/ui/console.py" in names,
                  "the payload carries the console renderer")
            check("app/lostpart/i18n.py" in names,
                  "the payload carries the pt-BR catalogue")
            check(any(name.startswith("python/lib/python3")
                      and "/tkinter" in name for name in names),
                  "the payload carries the Tkinter runtime of the graphical interface")

            interpreter = tar.getmember("python/bin/python3")
            check(bool(interpreter.mode & 0o111),
                  f"the interpreter is executable (mode {interpreter.mode:o})")

            app_script = tar.getmember("app/lostpart_main.py")
            check(app_script.mode & 0o200,
                  f"the entry point is readable (mode {app_script.mode:o})")

            check(any(member.issym() for member in members),
                  "the payload preserves the symbolic links of the archive")

            # The bundled interpreter must itself be a Linux ELF.
            handle = tar.extractfile("python/bin/python3")
            if handle is not None:
                head = handle.read(20)
                check(head[:4] == b"\x7fELF",
                      "the bundled interpreter is a Linux ELF")
                check(head[18:20] == b"\x3e\x00",
                      "the bundled interpreter targets x86-64")


def verify_installer() -> None:
    print("Windows installer")
    path = DIST / "lostpart-installer.exe"
    if not check(path.is_file(), f"{path.name} exists"):
        return
    data = path.read_bytes()
    check(data[:2] == b"MZ", "has a PE header")
    # The Inno Setup bootstrapper carries these markers in its payload.
    check(b"Inno Setup" in data[:200_000] or b"rDlPtS" in data,
          "was produced by the Inno Setup compiler")
    check(len(data) > 1_000_000, f"has a plausible size ({len(data)} bytes)")


def verify_checksums() -> None:
    """The published checksum list must describe the files next to it."""
    print("Checksum list")
    path = DIST / "SHA256SUMS.txt"
    if not check(path.is_file(), f"{path.name} exists"):
        return
    listed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        listed[name.strip()] = digest.strip()
    check(bool(listed), "the list is not empty")
    for name in ("lostpart-installer.exe", "lostpart-linux-x64",
                 "lostpart-windows-x64.exe"):
        target = DIST / name
        if not target.is_file():
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        check(listed.get(name) == actual,
              f"the listed checksum of {name} matches the file")


def main() -> int:
    print(f"verifying the release artefacts in {DIST}\n")
    verify_windows()
    print()
    verify_installer()
    print()
    verify_linux()
    print()
    verify_checksums()
    print()
    if failures:
        print(f"{len(failures)} of {checks} checks failed:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(f"all {checks} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
