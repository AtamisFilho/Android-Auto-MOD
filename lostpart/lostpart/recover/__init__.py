"""Recovery: writing a partition entry back to the disk."""

from __future__ import annotations

from .backup import TableBackup, create_backup, load_backup, restore_backup
from .writer import gpt_type_for_fs, mbr_type_for_fs, recover_partition, validate_candidate

__all__ = [
    "recover_partition",
    "validate_candidate",
    "mbr_type_for_fs",
    "gpt_type_for_fs",
    "TableBackup",
    "create_backup",
    "load_backup",
    "restore_backup",
]
