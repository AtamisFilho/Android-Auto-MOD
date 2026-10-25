"""lostpart -- identify and recover lost disk partitions.

The package provides a small, dependency free toolkit to:

* list the disks of a machine together with their partition tables;
* scan the free space of a disk for filesystems that have no partition entry;
* write the missing partition entry back, after taking a backup;
* browse the contents of a recovered partition without mounting it.

Everything is implemented from the public specifications of the on-disk
formats; the tool never needs the original vendor implementation.
"""

from __future__ import annotations

__version__ = "0.2.0"

from .errors import (
    DeviceError,
    DeviceReadOnlyError,
    FileSystemError,
    LostPartError,
    MountError,
    PartitionTableError,
    RecoveryError,
    ScanError,
    ValidationError,
)

__all__ = [
    "__version__",
    "LostPartError",
    "DeviceError",
    "DeviceReadOnlyError",
    "PartitionTableError",
    "FileSystemError",
    "RecoveryError",
    "ValidationError",
    "ScanError",
    "MountError",
]
