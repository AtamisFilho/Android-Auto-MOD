"""Exception hierarchy for :mod:`lostpart`.

Every error raised by the public API derives from :class:`LostPartError` so
callers can catch a single base class.  Errors that map to a concrete
remediation (for example "disk is read-only") carry that remediation inside
the message.
"""

from __future__ import annotations


class LostPartError(Exception):
    """Base class for every error raised by :mod:`lostpart`."""


class DeviceError(LostPartError):
    """The backing device could not be opened, queried or read/written."""


class DeviceReadOnlyError(DeviceError):
    """A write was attempted on a device that reports itself as read-only."""


class PermissionError_(DeviceError):
    """The OS denied access to the raw device (typically missing privileges)."""


class PartitionTableError(LostPartError):
    """The partition table could not be parsed or is inconsistent."""


class UnsupportedTableError(PartitionTableError):
    """The partition table type is neither MBR nor GPT."""


class FileSystemError(LostPartError):
    """A filesystem structure could not be parsed."""


class RecoveryError(LostPartError):
    """A recovery (write-back) operation failed."""


class ValidationError(RecoveryError):
    """The requested recovery was rejected by a pre-flight validation."""


class ScanError(LostPartError):
    """A scan could not be completed."""


class ScanCancelled(ScanError):
    """The scan was cancelled by the caller."""


class MountError(LostPartError):
    """A partition could not be mounted for browsing."""
