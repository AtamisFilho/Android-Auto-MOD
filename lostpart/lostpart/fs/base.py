"""Shared contracts for filesystem probes and readers.

A *probe* inspects the first few sectors of a candidate volume start and
decides whether a filesystem lives there.  A *reader* walks that filesystem
read-only so the contents of a recovered partition can be listed.

Both are exposed as plain module level functions so that every filesystem
module has exactly the same shape:

.. code-block:: python

    FS_TYPE = "ntfs"

    def detect(ctx: ProbeContext) -> ProbeResult | None: ...
    def read_directory(ctx: ProbeContext, path: tuple[str, ...] = ()) -> list[DirEntry]: ...

:func:`lostpart.fs.registry` collects the modules and dispatches to them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from ..device import RawDevice

__all__ = [
    "ProbeContext",
    "ProbeResult",
    "DirEntry",
    "FileSystemModule",
]


@dataclass(frozen=True)
class ProbeContext:
    """Everything a probe needs to inspect a candidate volume.

    All offsets used by the ``read`` helpers are **relative to the start of
    the candidate volume**, not to the disk.  ``start_sector`` is the volume
    start expressed in *device* sectors.
    """

    device: "RawDevice"
    start_sector: int
    sector_size: int
    total_sectors: int

    @property
    def byte_offset(self) -> int:
        """Byte offset of the volume start inside the device."""
        return self.start_sector * self.sector_size

    def read(self, offset: int, size: int) -> bytes:
        """Read ``size`` bytes at ``offset`` bytes from the volume start."""
        return self.device.read_at(self.byte_offset + offset, size)

    def read_sector(self, index: int, count: int = 1) -> bytes:
        """Read ``count`` device sectors starting at device sector ``index``."""
        return self.device.read_at(index * self.sector_size, count * self.sector_size)

    def volume_bytes(self) -> int:
        """Total number of bytes spanned by the candidate volume."""
        return max(0, (self.total_sectors - self.start_sector) * self.sector_size)


@dataclass(frozen=True)
class ProbeResult:
    """Verdict produced by a filesystem probe.

    ``confidence`` is a value between 0.0 and 1.0 expressing how sure the
    probe is that a filesystem of this type starts here.  ``evidence`` lists
    the concrete reasons, so a user can audit why a candidate was reported.
    """

    fs_type: str
    label: str
    confidence: float
    details: dict[str, object] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()

    @property
    def size_sectors(self) -> int | None:
        """Total size of the volume in device sectors, when known."""
        value = self.details.get("total_sectors")
        return int(value) if isinstance(value, int) else None

    @property
    def bytes_per_sector(self) -> int | None:
        value = self.details.get("bytes_per_sector")
        return int(value) if isinstance(value, int) else None

    @property
    def sectors_per_cluster(self) -> int | None:
        value = self.details.get("sectors_per_cluster")
        return int(value) if isinstance(value, int) else None


@dataclass(frozen=True)
class DirEntry:
    """A single directory entry produced by a filesystem reader."""

    name: str
    is_dir: bool
    size: int = 0
    modified: float | None = None
    inode: int | None = None
    is_hidden: bool = False

    def __str__(self) -> str:  # pragma: no cover - display helper
        kind = "d" if self.is_dir else "-"
        return f"{kind} {self.name} ({self.size})"


class FileSystemModule(Protocol):
    """Structural type of a filesystem module (checked at import time)."""

    FS_TYPE: str

    def detect(self, ctx: ProbeContext) -> ProbeResult | None: ...

    def read_directory(
        self, ctx: ProbeContext, path: tuple[str, ...] = ()
    ) -> list[DirEntry]: ...
