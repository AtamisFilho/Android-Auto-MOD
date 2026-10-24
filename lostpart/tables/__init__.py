"""Partition table parsing and building."""

from __future__ import annotations

from .table import (
    TABLE_TYPE_GPT,
    TABLE_TYPE_MBR,
    TABLE_TYPE_NONE,
    PartitionEntry,
    PartitionTable,
    detect_table_type,
    load_partition_table,
)

__all__ = [
    "PartitionEntry",
    "PartitionTable",
    "detect_table_type",
    "load_partition_table",
    "TABLE_TYPE_MBR",
    "TABLE_TYPE_GPT",
    "TABLE_TYPE_NONE",
]
