#!/usr/bin/env python3
"""Build the standalone binaries of lostpart.

Two targets are available:

``windows``
    A single ``lostpart.exe`` built with PyInstaller.  It bundles the
    interpreter and the whole standard library, so it runs on any Windows x64
    machine without Python installed.

``linux``
    A single statically linked x86-64 ELF that carries the application and a
    static (musl) CPython inside itself.  It runs on any Linux x64 machine
    without Python installed and without depending on the system libc.

Both targets are cross buildable from any host: the Linux binary is produced
with the Zig compiler, which can target ``x86_64-linux-musl`` directly.

Usage::

    python scripts/build.py windows
    python scripts/build.py linux
    python scripts/build.py all
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"

#: The static CPython used for the Linux build.  It is built against musl, so
#: the resulting binary does not depend on the libc of the target machine.
CPYTHON_TAG = "20261021"
CPYTHON_VERSION = "3.13.17"
CPYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{CPYTHON_TAG}/cpython-{CPYTHON_VERSION}%2B{CPYTHON_TAG}"
    "-x86_64-unknown-linux-musl-install_only_stripped.tar.gz"
)

PAYLOAD_MAGIC = b"LOSTPART_PAYLOAD_V1\n"
TRAILER_MAGIC = b"LOSTPART_END_V1\n"


def project_version() -> str:
    """Read the version from the package without importing it."""
    text = (ROOT / "lostpart" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "0.0.0"


def log(message: str) -> None:
    print(f"[build] {message}", flush=True)


def run(command: list[str], cwd: Path | None = None) -> None:
    log(" ".join(command))
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(f"command failed with exit code {result.returncode}")


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------


def build_windows() -> Path:
    """Build the Windows executable with PyInstaller."""
    version = project_version()
    DIST.mkdir(parents=True, exist_ok=True)
    name = "lostpart-windows-x64.exe"

    command = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",
        "--clean",
        "--noconfirm",
        "--name", "lostpart",
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
        "--paths", str(ROOT),
        # The filesystem modules are loaded through importlib at run time, so
        # the static analysis cannot see them.
        "--collect-submodules", "lostpart",
        "--hidden-import", "sqlite3",
    ]
    icon = ROOT / "assets" / "lostpart.ico"
    if icon.is_file():
        command += ["--icon", str(icon)]
    else:
        log("the icon is missing, run scripts/make_icon.py first")
    if sys.platform == "win32":
        version_file = BUILD / "version_info.txt"
        version_file.parent.mkdir(parents=True, exist_ok=True)
        version_file.write_text(_windows_version_info(version), encoding="utf-8")
        command += ["--version-file", str(version_file)]
    command.append(str(ROOT / "scripts" / "lostpart_main.py"))
    run(command, cwd=ROOT)

    produced = DIST / ("lostpart.exe" if sys.platform == "win32" else "lostpart")
    target = DIST / name
    if produced != target:
        if target.exists():
            target.unlink()
        shutil.move(str(produced), str(target))
    log(f"built {target} ({target.stat().st_size} bytes)")
    return target


def _windows_version_info(version: str) -> str:
    parts = version.split(".")
    while len(parts) < 4:
        parts.append("0")
    major, minor, patch, build = (int(p) for p in parts[:4])
    return (
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers=({major}, {minor}, {patch}, {build}),\n"
        f"                prodvers=({major}, {minor}, {patch}, {build}),\n"
        "                mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,\n"
        "                subtype=0x0, date=(0, 0)),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable('040904B0', [\n"
        "        StringStruct('CompanyName', 'Atamis Filho'),\n"
        "        StringStruct('FileDescription', 'lostpart - lost partition recovery'),\n"
        f"        StringStruct('FileVersion', '{version}'),\n"
        "        StringStruct('InternalName', 'lostpart'),\n"
        "        StringStruct('OriginalFilename', 'lostpart.exe'),\n"
        "        StringStruct('ProductName', 'lostpart'),\n"
        f"        StringStruct('ProductVersion', '{version}')])\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])])\n"
        "  ]\n"
        ")\n"
    )


# --------------------------------------------------------------------------
# Linux
# --------------------------------------------------------------------------


def _download(url: str, destination: Path) -> Path:
    if destination.exists() and destination.stat().st_size > 0:
        log(f"using the cached {destination.name}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    log(f"downloading {url}")
    with urllib.request.urlopen(url) as response, open(destination, "wb") as out:
        shutil.copyfileobj(response, out)
    return destination


def _zig() -> list[str]:
    """Return the command that invokes the Zig compiler."""
    if shutil.which("zig"):
        return ["zig", "cc"]
    try:
        import ziglang  # noqa: F401
    except ImportError:
        raise SystemExit(
            "the Zig compiler is required to build the Linux binary.\n"
            "Install it with:  pip install ziglang"
        )
    return [sys.executable, "-m", "ziglang", "cc"]


def build_linux() -> Path:
    """Build the Linux executable: a static ELF with the payload appended."""
    version = project_version()
    DIST.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    target = DIST / "lostpart-linux-x64"

    archive = _download(CPYTHON_URL, BUILD / "downloads" / Path(CPYTHON_URL).name)

    # The application is staged on disk and appended to the payload; the
    # CPython archive is copied member by member so that the permissions and
    # the symbolic links it carries survive into the Linux tar.
    staging = BUILD / "linux"
    if staging.exists():
        shutil.rmtree(staging)
    app_dir = staging / "app"
    app_dir.mkdir(parents=True)
    shutil.copytree(ROOT / "lostpart", app_dir / "lostpart",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "scripts" / "lostpart_main.py", app_dir / "lostpart_main.py")

    payload = BUILD / "payload.tar.gz"
    log("packing the payload")
    with tarfile.open(archive, "r:gz") as source, tarfile.open(payload, "w:gz",
                                                                compresslevel=9) as out:
        for member in source.getmembers():
            handle = source.extractfile(member) if member.isfile() else None
            out.addfile(member, handle)

        for path in sorted(app_dir.rglob("*")):
            arcname = str(path.relative_to(staging)).replace(os.sep, "/")
            if path.is_dir():
                info = tarfile.TarInfo(arcname + "/")
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                out.addfile(info)
                continue
            info = out.gettarinfo(str(path), arcname=arcname)
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mode = 0o755 if info.mode & 0o111 else 0o644
            with open(path, "rb") as handle:
                out.addfile(info, handle)

    shutil.rmtree(staging, ignore_errors=True)

    launcher = BUILD / "launcher-linux"
    log("compiling the static launcher")
    command = _zig() + [
        "-target", "x86_64-linux-musl",
        "-static",
        "-O2",
        "-s",  # strip
        f"-DLOSTPART_VERSION=\"{version}\"",
        str(ROOT / "scripts" / "launcher.c"),
        "-o", str(launcher),
    ]
    run(command, cwd=ROOT)

    log("assembling the executable")
    with open(target, "wb") as out:
        out.write(launcher.read_bytes())
        offset = out.tell()
        out.write(payload.read_bytes())
        size = payload.stat().st_size
        out.write(struct.pack("<QQ", offset, size))
        out.write(PAYLOAD_MAGIC)
        out.write(TRAILER_MAGIC)
    launcher.unlink(missing_ok=True)

    log(f"built {target} ({target.stat().st_size} bytes)")
    return target


# --------------------------------------------------------------------------
# Windows installer
# --------------------------------------------------------------------------


def _iscc() -> str:
    """Locate the Inno Setup compiler."""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("ISCC")
    if found:
        return found
    raise SystemExit(
        "the Inno Setup compiler was not found.\n"
        "Install it with:  winget install --id JRSoftware.InnoSetup -e\n"
        "or download it from https://jrsoftware.org/isdl.php"
    )


def build_installer() -> Path:
    """Compile the Windows installer with Inno Setup."""
    template = ROOT / "installer" / "lostpart.iss"
    if not template.is_file():
        raise SystemExit(f"{template} does not exist")
    DIST.mkdir(parents=True, exist_ok=True)

    # The script is copied with the version of the package substituted, so
    # the installer can never carry a stale version.
    version = project_version()
    generated = template.with_name("lostpart.generated.iss")
    text = template.read_text(encoding="utf-8")
    text = re.sub(r'#define AppVersion "[^"]*"', f'#define AppVersion "{version}"', text)
    generated.write_text(text, encoding="utf-8")

    log("compiling the installer")
    run([_iscc(), str(generated)], cwd=generated.parent)
    target = DIST / "lostpart-installer.exe"
    log(f"built {target} ({target.stat().st_size} bytes)")
    return target


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the lostpart binaries.")
    parser.add_argument(
        "target",
        choices=["windows", "linux", "installer", "all"],
        help="windows: the portable executable; linux: the static ELF; "
             "installer: the Inno Setup installer; all: everything",
    )
    args = parser.parse_args(argv)

    if args.target in ("windows", "all"):
        build_windows()
    if args.target in ("linux", "all"):
        build_linux()
    if args.target in ("installer", "all"):
        build_installer()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
