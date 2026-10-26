"""Raw device access layer.

The rest of :mod:`lostpart` only ever talks to a :class:`RawDevice`, which
exposes a flat byte-addressed view of a physical disk.  Three backends are
provided:

* :class:`FileDevice` -- a regular file or a disk image.  Useful for tests,
  for forensic work on images and for recovering from an LVM/RAID member.
* :class:`WindowsPhysicalDrive` -- ``\\\\.\\PhysicalDriveN`` on Windows.
* :class:`LinuxBlockDevice` -- ``/dev/sdX``, ``/dev/nvme0n1`` ... on Linux.

Both OS backends query the *logical* sector size reported by the device so
that 512e (Advanced Format) and 4Kn drives are handled correctly.
"""

from __future__ import annotations

import os
import stat
from abc import ABC, abstractmethod
from typing import Final

from .errors import DeviceError, DeviceReadOnlyError, PermissionError_
from .i18n import t

__all__ = [
    "RawDevice",
    "FileDevice",
    "WindowsPhysicalDrive",
    "LinuxBlockDevice",
    "open_device",
    "list_physical_devices",
    "list_physical_device_specs",
]


class RawDevice(ABC):
    """Byte-addressed view of a block device."""

    #: Logical sector size in bytes.
    sector_size: int = 512
    #: Total size of the device in bytes.
    size: int = 0

    @property
    def total_sectors(self) -> int:
        """Number of logical sectors addressable on the device."""
        if self.sector_size <= 0:
            return 0
        return self.size // self.sector_size

    @property
    def is_readonly(self) -> bool:
        """True when the device refuses writes."""
        return False

    @abstractmethod
    def read_at(self, offset: int, size: int) -> bytes:
        """Read exactly ``size`` bytes starting at byte ``offset``."""

    @abstractmethod
    def write_at(self, offset: int, data: bytes) -> None:
        """Write ``data`` at byte ``offset``."""

    def close(self) -> None:  # pragma: no cover - default is a no-op
        """Release any underlying handle."""

    def __enter__(self) -> "RawDevice":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<{type(self).__name__} size={self.size} sector_size={self.sector_size} "
            f"readonly={self.is_readonly}>"
        )


class FileDevice(RawDevice):
    """A device backed by a regular file (disk image)."""

    def __init__(self, path: str | os.PathLike[str], read_only: bool = False) -> None:
        self.path = os.fspath(path)
        self._read_only = read_only
        try:
            self._fh = open(self.path, "rb" if read_only else "r+b")
        except PermissionError as exc:
            raise PermissionError_(
                t("error.open_device", path=self.path, error=exc)
            ) from exc
        except OSError as exc:
            raise DeviceError(
                t("error.open_device", path=self.path, error=exc)
            ) from exc
        self.size = os.fstat(self._fh.fileno()).st_size
        self.sector_size = 512

    def read_at(self, offset: int, size: int) -> bytes:
        if size < 0 or offset < 0:
            raise DeviceError("negative offset or size")
        self._fh.seek(offset)
        data = self._fh.read(size)
        if len(data) != size:
            raise DeviceError(
                f"short read at offset {offset}: wanted {size} bytes, got {len(data)}"
            )
        return data

    def write_at(self, offset: int, data: bytes) -> None:
        if self._read_only:
            raise DeviceReadOnlyError(f"{self.path} was opened read-only")
        self._fh.seek(offset)
        self._fh.write(data)
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:  # pragma: no cover - best effort
            pass


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------

if os.name == "nt":  # pragma: no cover - platform specific
    import ctypes
    import ctypes.wintypes as wintypes

    _GENERIC_READ: Final = 0x80000000
    _GENERIC_WRITE: Final = 0x40000000
    _FILE_SHARE_READ: Final = 0x00000001
    _FILE_SHARE_WRITE: Final = 0x00000002
    _OPEN_EXISTING: Final = 3
    _FILE_ATTRIBUTE_NORMAL: Final = 0x00000080
    _ERROR_ACCESS_DENIED: Final = 5
    _ERROR_WRITE_PROTECT: Final = 19
    _ERROR_NOT_SUPPORTED: Final = 50
    _IOCTL_DISK_GET_DRIVE_GEOMETRY_EX: Final = 0x000700A0
    _IOCTL_DISK_GET_LENGTH_INFO: Final = 0x0007407C
    _IOCTL_DISK_IS_WRITABLE: Final = 0x00074024

    class _DISK_GEOMETRY_EX(ctypes.Structure):
        _fields_ = [
            ("Geometry", ctypes.c_byte * 4),
            ("DiskSize", ctypes.c_longlong),
            ("PartitionLength", ctypes.c_longlong),
            ("PartitionOffset", ctypes.c_longlong),
            ("Alignment", ctypes.c_ulong * 4),
        ]

    class _GET_LENGTH_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("Length", ctypes.c_longlong),
            ("Alignment", ctypes.c_ulong),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.ReadFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    _kernel32.ReadFile.restype = wintypes.BOOL
    _kernel32.WriteFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    _kernel32.WriteFile.restype = wintypes.BOOL
    _kernel32.SetFilePointerEx.argtypes = [
        wintypes.HANDLE, ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD,
    ]
    _kernel32.SetFilePointerEx.restype = wintypes.BOOL
    _kernel32.DeviceIoControl.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    _kernel32.DeviceIoControl.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.GetLastError.restype = wintypes.DWORD

    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class WindowsPhysicalDrive(RawDevice):  # pragma: no cover - platform specific
    """Access a Windows physical disk through ``\\\\.\\PhysicalDriveN``."""

    def __init__(self, index: int, read_only: bool = False) -> None:
        if os.name != "nt":
            raise DeviceError("WindowsPhysicalDrive is only available on Windows")
        self.index = int(index)
        self.path = rf"\\.\PhysicalDrive{self.index}"
        access = _GENERIC_READ if read_only else (_GENERIC_READ | _GENERIC_WRITE)
        handle = _kernel32.CreateFileW(
            self.path, access, _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None, _OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL, None,
        )
        if handle == INVALID_HANDLE_VALUE:
            err = _kernel32.GetLastError()
            if err == _ERROR_ACCESS_DENIED:
                raise PermissionError_(
                    t("error.access_denied", path=self.path)
                )
            raise DeviceError(
                t("error.open_device", path=self.path,
                  error=f"erro do Windows {err}")
            )
        self._handle = handle
        self.sector_size = self._query_sector_size()
        self.size = self._query_size()
        self._readonly = read_only or not self._query_writable()

    # -- helpers ---------------------------------------------------------
    def _ioctl(self, code: int, in_buf: int = 0, in_size: int = 0,
               out_size: int = 0) -> bytes:
        out = ctypes.create_string_buffer(out_size) if out_size else None
        returned = wintypes.DWORD(0)
        ok = _kernel32.DeviceIoControl(
            self._handle, code, None if not in_buf else ctypes.c_void_p(in_buf),
            in_size, ctypes.cast(out, ctypes.c_void_p) if out else None,
            out_size, ctypes.byref(returned), None,
        )
        if not ok:
            err = _kernel32.GetLastError()
            raise DeviceError(f"DeviceIoControl(0x{code:X}) failed: Win32 error {err}")
        return out.raw[: returned.value] if out else b""

    def _query_sector_size(self) -> int:
        raw = self._ioctl(_IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, out_size=256)
        geom = _DISK_GEOMETRY_EX.from_buffer_copy(raw[: ctypes.sizeof(_DISK_GEOMETRY_EX)])
        return int(geom.Geometry[0]) or 512

    def _query_size(self) -> int:
        raw = self._ioctl(_IOCTL_DISK_GET_LENGTH_INFO, out_size=ctypes.sizeof(_GET_LENGTH_INFORMATION))
        info = _GET_LENGTH_INFORMATION.from_buffer_copy(raw[: ctypes.sizeof(_GET_LENGTH_INFORMATION)])
        return int(info.Length)

    def _query_writable(self) -> bool:
        try:
            self._ioctl(_IOCTL_DISK_IS_WRITABLE)
        except DeviceError:
            return False
        return True

    # -- RawDevice API --------------------------------------------------
    @property
    def is_readonly(self) -> bool:
        return self._readonly

    def read_at(self, offset: int, size: int) -> bytes:
        if size < 0 or offset < 0:
            raise DeviceError("negative offset or size")
        buf = ctypes.create_string_buffer(size)
        read = wintypes.DWORD(0)
        if not _kernel32.SetFilePointerEx(
            self._handle, ctypes.c_longlong(offset), None, 0
        ):
            err = _kernel32.GetLastError()
            raise DeviceError(f"seek to {offset} failed: Win32 error {err}")
        if not _kernel32.ReadFile(self._handle, buf, size, ctypes.byref(read), None):
            err = _kernel32.GetLastError()
            raise DeviceError(f"read at {offset} failed: Win32 error {err}")
        if read.value != size:
            raise DeviceError(f"short read at {offset}: wanted {size}, got {read.value}")
        return buf.raw[:size]

    def write_at(self, offset: int, data: bytes) -> None:
        if self._readonly:
            raise DeviceReadOnlyError(f"{self.path} is read-only")
        buf = ctypes.create_string_buffer(data, len(data))
        written = wintypes.DWORD(0)
        if not _kernel32.SetFilePointerEx(
            self._handle, ctypes.c_longlong(offset), None, 0
        ):
            err = _kernel32.GetLastError()
            raise DeviceError(f"seek to {offset} failed: Win32 error {err}")
        if not _kernel32.WriteFile(self._handle, buf, len(data), ctypes.byref(written), None):
            err = _kernel32.GetLastError()
            if err == _ERROR_WRITE_PROTECT:
                raise DeviceReadOnlyError(f"{self.path} is write protected")
            raise DeviceError(f"write at {offset} failed: Win32 error {err}")
        if written.value != len(data):
            raise DeviceError(f"short write at {offset}: wanted {len(data)}, wrote {written.value}")

    def close(self) -> None:
        if getattr(self, "_handle", None):
            _kernel32.CloseHandle(self._handle)
            self._handle = None


# --------------------------------------------------------------------------
# Linux
# --------------------------------------------------------------------------

if os.name == "posix":  # pragma: no cover - platform specific
    import ctypes
    import ctypes.util

    _BLKGETSIZE64: Final = 0x80081272
    _BLKSSZGET: Final = 0x1268
    _BLKRO: Final = 0x125E

    _libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
    _libc.ioctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p]
    _libc.ioctl.restype = ctypes.c_int
    _libc.pread.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_longlong]
    _libc.pread.restype = ctypes.c_ssize_t
    _libc.pwrite.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_longlong]
    _libc.pwrite.restype = ctypes.c_ssize_t


class LinuxBlockDevice(RawDevice):  # pragma: no cover - platform specific
    """Access a Linux block device such as ``/dev/sda``."""

    def __init__(self, path: str | os.PathLike[str], read_only: bool = False) -> None:
        if os.name != "posix":
            raise DeviceError("LinuxBlockDevice is only available on POSIX systems")
        self.path = os.fspath(path)
        try:
            self._fd = os.open(self.path, os.O_RDONLY if read_only else os.O_RDWR)
        except PermissionError as exc:
            raise PermissionError_(
                t("error.open_device", path=self.path, error=exc)
            ) from exc
        except OSError as exc:
            raise DeviceError(
                t("error.open_device", path=self.path, error=exc)
            ) from exc
        self.sector_size = self._query_sector_size()
        self.size = self._query_size()
        self._readonly = read_only or not self._query_writable()

    def _ioctl(self, request: int, arg: int = 0) -> int:
        ctypes.set_errno(0)
        res = _libc.ioctl(self._fd, request, ctypes.byref(ctypes.c_int(arg)))
        if res < 0:
            err = ctypes.get_errno()
            raise DeviceError(f"ioctl(0x{request:X}) on {self.path} failed: errno {err}")
        return res

    def _query_sector_size(self) -> int:
        buf = ctypes.c_int(0)
        ctypes.set_errno(0)
        if _libc.ioctl(self._fd, _BLKSSZGET, ctypes.byref(buf)) < 0:
            return 512
        return int(buf.value) or 512

    def _query_size(self) -> int:
        buf = ctypes.c_longlong(0)
        ctypes.set_errno(0)
        if _libc.ioctl(self._fd, _BLKGETSIZE64, ctypes.byref(buf)) < 0:
            # Fall back to the file size for device-mapper style devices.
            try:
                return os.stat(self.path).st_size
            except OSError as exc:
                raise DeviceError(f"cannot determine size of {self.path}: {exc}") from exc
        return int(buf.value)

    def _query_writable(self) -> bool:
        try:
            buf = ctypes.c_int(0)
            ctypes.set_errno(0)
            if _libc.ioctl(self._fd, _BLKRO, ctypes.byref(buf)) < 0:
                return True
            return buf.value == 0
        except DeviceError:
            return True

    @property
    def is_readonly(self) -> bool:
        return self._readonly

    def read_at(self, offset: int, size: int) -> bytes:
        if size < 0 or offset < 0:
            raise DeviceError("negative offset or size")
        buf = ctypes.create_string_buffer(size)
        got = _libc.pread(self._fd, buf, size, offset)
        if got != size:
            raise DeviceError(f"short read at {offset}: wanted {size}, got {got}")
        return buf.raw[:size]

    def write_at(self, offset: int, data: bytes) -> None:
        if self._readonly:
            raise DeviceReadOnlyError(f"{self.path} is read-only")
        buf = ctypes.create_string_buffer(data, len(data))
        put = _libc.pwrite(self._fd, buf, len(data), offset)
        if put != len(data):
            raise DeviceError(f"short write at {offset}: wanted {len(data)}, wrote {put}")

    def close(self) -> None:
        if getattr(self, "_fd", None) is not None:
            os.close(self._fd)
            self._fd = None


# --------------------------------------------------------------------------
# Discovery helpers
# --------------------------------------------------------------------------


def list_physical_devices() -> list[RawDevice]:
    """Enumerate physical disks available to the current user.

    Returns an empty list when the platform is unsupported or the user lacks
    the privileges to open the devices.
    """
    devices: list[RawDevice] = []
    if os.name == "nt":  # pragma: no cover - platform specific
        import ctypes

        for index in range(0, 64):
            try:
                devices.append(WindowsPhysicalDrive(index, read_only=True))
            except (DeviceError, PermissionError_):
                continue
        return devices
    if os.name == "posix":  # pragma: no cover - platform specific
        import glob

        for path in sorted(glob.glob("/dev/sd*") + glob.glob("/dev/nvme*n*") +
                           glob.glob("/dev/vd*") + glob.glob("/dev/xvd*")):
            try:
                st = os.stat(path)
            except OSError:
                continue
            if not stat.S_ISBLK(st.st_mode):
                continue
            try:
                devices.append(LinuxBlockDevice(path, read_only=True))
            except (DeviceError, PermissionError_):
                continue
        return devices
    return devices


def list_physical_device_specs() -> list[str]:
    """Enumerate the physical disks of the machine, without opening them.

    The result holds the specifications understood by :func:`open_device`,
    so the caller can open the ones it is interested in.  Disks that cannot
    be opened at all -- because they are locked by another program, or
    because the user lacks the privileges -- are simply left out.
    """
    specs: list[str] = []
    if os.name == "nt":  # pragma: no cover - platform specific
        for index in range(0, 32):
            try:
                probe = WindowsPhysicalDrive(index, read_only=True)
            except (DeviceError, PermissionError_):
                continue
            probe.close()
            specs.append(str(index))
        return specs
    if os.name == "posix":  # pragma: no cover - platform specific
        import glob

        for path in sorted(glob.glob("/dev/sd*") + glob.glob("/dev/nvme*n*") +
                           glob.glob("/dev/vd*") + glob.glob("/dev/xvd*")):
            try:
                st = os.stat(path)
            except OSError:
                continue
            if not stat.S_ISBLK(st.st_mode):
                continue
            specs.append(path)
        return specs
    return specs


def open_device(spec: str, read_only: bool = False) -> RawDevice:
    """Open a device from a user supplied specification.

    Accepted forms:

    * ``N`` or ``disk:N`` -- physical disk number (Windows ``PhysicalDriveN``,
      Linux ``/dev/sdN``).
    * a path that exists on disk -- opened as a file or block device.
    * ``\\\\.\\PhysicalDriveN`` -- explicit Windows path.
    """
    spec = spec.strip()
    if not spec:
        raise DeviceError(t("error.empty_device"))

    if spec.lower().startswith("disk:"):
        spec = spec.split(":", 1)[1].strip()

    if spec.lower().startswith("\\\\.\\physicaldrive"):
        index = spec.rsplit("physicaldrive", 1)[1]
        return WindowsPhysicalDrive(int(index), read_only=read_only)

    if spec.isdigit():
        index = int(spec)
        if os.name == "nt":
            return WindowsPhysicalDrive(index, read_only=read_only)
        if os.name == "posix":
            return LinuxBlockDevice(f"/dev/sd{index}", read_only=read_only)
        raise DeviceError(t("error.numeric_device"))

    if os.path.exists(spec):
        if os.name == "posix" and stat.S_ISBLK(os.stat(spec).st_mode):
            return LinuxBlockDevice(spec, read_only=read_only)
        return FileDevice(spec, read_only=read_only)

    raise DeviceError(t("error.unknown_device", spec=spec))
