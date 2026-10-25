# Building the binaries

`lostpart` is pure Python with no runtime dependencies, so it can be used
straight from a checkout.  The release binaries bundle an interpreter so that
they run on machines that have no Python installed.

## Quick start

```bash
git clone https://github.com/AtamisFilho/testes.git
cd testes/lostpart

python -m venv .venv
.venv/Scripts/activate          # . .venv/bin/activate on Linux
pip install -e ".[dev]"

python -m pytest
```

That is all you need to *run* the tool.  To produce the standalone binaries
you need a bit more.

## Standalone binaries

```bash
pip install pyinstaller ziglang
python scripts/make_icon.py        # once, generates assets/lostpart.ico
python scripts/build.py windows     # -> dist/lostpart-windows-x64.exe
python scripts/build.py linux       # -> dist/lostpart-linux-x64
python scripts/build.py installer   # -> dist/lostpart-installer.exe
python scripts/build.py all         # everything
```

### Windows

The Windows binary is built with [PyInstaller](https://pyinstaller.org) as a
one-file executable.  It embeds the interpreter and the whole standard
library, so it runs on any Windows x64 machine without Python.

The filesystem modules are loaded with `importlib` at run time, so the build
passes `--collect-submodules lostpart`; without it the packaged binary would
come up with only the NTFS probe available.

### Windows installer

The installer is built with [Inno Setup](https://jrsoftware.org).  The script
lives in `installer/lostpart.iss`; `scripts/build.py` copies it to
`lostpart.generated.iss` with the version of the package substituted, so the
installer can never carry a stale version.

```bash
winget install --id JRSoftware.InnoSetup -e
python scripts/build.py installer
```

The installation is per user: `PrivilegesRequired=lowest` puts it under
`%LOCALAPPDATA%\Programs\lostpart` and it never asks for administrator
rights.  It adds the Start Menu entries, offers to add the program to the
`PATH`, registers itself in *Apps & features* and installs an uninstaller.

The Inno Setup compiler is located automatically in the usual places:

```
%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
C:\Program Files (x86)\Inno Setup 6\ISCC.exe
```

### Linux

The Linux binary is a statically linked `x86_64-linux-musl` ELF with a
compressed payload appended to it:

```
[static ELF launcher][payload.tar.gz][trailer]
```

The launcher is ~150 lines of C (`scripts/launcher.c`).  At run time it

1. finds itself through `/proc/self/exe`;
2. reads the trailer to learn the payload offset and size;
3. unpacks the payload into `~/.cache/lostpart/<version>/` with the system
   `tar`, skipping the work when the cache is already populated;
4. execs the bundled interpreter with the bundled application.

The interpreter is the static (musl) build of CPython published by
[python-build-standalone](https://github.com/astral-sh/python-build-standalone).
Because it is built against musl, the binary does not depend on the libc of
the target machine and runs on any Linux x64 distribution.

The launcher is compiled with the [Zig](https://ziglang.org) compiler, which
can target `x86_64-linux-musl` from any host:

```bash
zig cc -target x86_64-linux-musl -static -O2 -s \
    -DLOSTPART_VERSION='"0.1.0"' scripts/launcher.c -o launcher
```

Because Zig cross-compiles, the Linux binary can be produced from Windows or
macOS without a Linux host.  The only network access the build needs is the
download of the CPython archive, which is cached under `build/downloads/`.

### Verifying a build

```bash
python scripts/verify_release.py
```

The script checks the PE header of the Windows executable, the Inno Setup
bootstrapper, and -- for the Linux binary -- the ELF header, the absence of a
dynamic loader, the payload trailer, the contents of the payload and the
permissions of the bundled interpreter.

A quick manual check:

```bash
# Windows
dist\lostpart-windows-x64.exe --version
dist\lostpart-windows-x64.exe --help

# Linux
chmod +x dist/lostpart-linux-x64
./dist/lostpart-linux-x64 --version
./dist/lostpart-linux-x64 --help
file dist/lostpart-linux-x64
```

`file` should report an `ELF 64-bit LSB executable, x86-64` — the payload is
appended after the ELF image and does not change that.

## Release checklist

1. Bump `__version__` in `lostpart/__init__.py` and add an entry to
   `CHANGELOG.md`.
2. `python scripts/make_icon.py` when the icon changed.
3. `python scripts/build.py all`
4. `python scripts/verify_release.py`
5. `python -m pytest`
6. Tag and publish:

   ```bash
   git tag -a v0.2.0 -m "lostpart 0.2.0"
   git push origin main --tags
   gh release create v0.2.0 \
       dist/lostpart-installer.exe \
       dist/lostpart-windows-x64.exe \
       dist/lostpart-linux-x64 \
       --title "lostpart 0.2.0" \
       --notes-file docs/releases/v0.2.0.md
   ```

## Layout of the build directory

```
build/
├── downloads/            cached CPython archive
├── linux/                staging area for the Linux payload
├── payload.tar.gz        the payload that gets appended
├── pyinstaller/          PyInstaller work directory
└── version_info.txt      Windows version resource
dist/
├── lostpart-installer.exe
├── lostpart-windows-x64.exe
└── lostpart-linux-x64
```

Both `build/` and `dist/` are ignored by git.
