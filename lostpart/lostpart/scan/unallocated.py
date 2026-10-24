"""Compute the unallocated regions of a disk.

The region between two partitions -- and the region before the first and
after the last partition -- is free space.  Those are exactly the places
where a lost partition can hide: a volume whose entry was removed still owns
its sectors, and those sectors are now reported as free.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..tables.table import PartitionEntry

__all__ = ["UnallocatedRegion", "compute_unallocated_regions"]


@dataclass(frozen=True)
class UnallocatedRegion:
    """A contiguous range of sectors that belongs to no partition."""

    start_sector: int
    sector_count: int

    @property
    def end_sector(self) -> int:
        """First sector after the region."""
        return self.start_sector + self.sector_count

    @property
    def size_bytes(self) -> int:
        return self.sector_count

    def contains(self, sector: int) -> bool:
        return self.start_sector <= sector < self.end_sector

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"[{self.start_sector}, {self.end_sector}) {self.sector_count} sectors"


def compute_unallocated_regions(
    entries: list[PartitionEntry],
    area_start: int,
    area_end: int,
    merge_gap_sectors: int = 0,
) -> list[UnallocatedRegion]:
    """Return the free regions of a disk.

    ``area_start`` and ``area_end`` bound the area that may hold partitions
    (for GPT this is the range between ``first_usable_lba`` and
    ``last_usable_lba``; for MBR it is LBA 1 to the end of the disk).

    ``merge_gap_sectors`` joins two free regions that are separated by an
    occupied span of at most that many sectors.  This is useful when the
    partition table contains a stray entry that only covers a few sectors
    but still splits the free space in two.
    """
    if area_end <= area_start:
        return []

    occupied = sorted(
        (e for e in entries if not e.is_empty),
        key=lambda e: e.start_lba,
    )

    regions: list[UnallocatedRegion] = []
    cursor = area_start
    for entry in occupied:
        start = max(entry.start_lba, area_start)
        end = min(entry.end_lba, area_end)
        if end <= area_start or start >= area_end:
            continue
        if start > cursor:
            regions.append(UnallocatedRegion(cursor, start - cursor))
        cursor = max(cursor, end)
    if cursor < area_end:
        regions.append(UnallocatedRegion(cursor, area_end - cursor))

    regions = [r for r in regions if r.sector_count > 0]

    if merge_gap_sectors > 0 and len(regions) > 1:
        merged = [regions[0]]
        for region in regions[1:]:
            previous = merged[-1]
            separator = region.start_sector - previous.end_sector
            if 0 < separator <= merge_gap_sectors:
                merged[-1] = UnallocatedRegion(
                    previous.start_sector, region.end_sector - previous.start_sector
                )
            else:
                merged.append(region)
        regions = merged

    return regions
