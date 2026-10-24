"""Tests for the free space computation."""

from __future__ import annotations

from lostpart.scan.unallocated import compute_unallocated_regions
from lostpart.tables.table import PartitionEntry


def entry(index: int, start: int, count: int) -> PartitionEntry:
    return PartitionEntry(
        index=index,
        start_lba=start,
        sector_count=count,
        label="test",
        type_code="0x07",
    )


def test_a_single_partition_leaves_two_free_regions():
    regions = compute_unallocated_regions([entry(0, 2048, 2048)], 1, 10000)
    assert len(regions) == 2
    assert regions[0].start_sector == 1
    assert regions[0].sector_count == 2047
    assert regions[1].start_sector == 4096
    assert regions[1].sector_count == 10000 - 4096


def test_the_gap_between_two_partitions_is_free():
    regions = compute_unallocated_regions(
        [entry(0, 2048, 2048), entry(1, 8192, 2048)], 1, 20000
    )
    assert len(regions) == 3
    assert regions[1].start_sector == 4096
    assert regions[1].sector_count == 8192 - 4096


def test_adjacent_partitions_produce_no_gap():
    regions = compute_unallocated_regions(
        [entry(0, 2048, 2048), entry(1, 4096, 2048)], 1, 10000
    )
    assert len(regions) == 2
    assert all(region.sector_count > 0 for region in regions)


def test_empty_partitions_are_ignored():
    regions = compute_unallocated_regions(
        [entry(0, 2048, 2048), entry(1, 0, 0)], 1, 10000
    )
    assert len(regions) == 2


def test_free_regions_separated_by_a_tiny_partition_can_be_merged():
    # A stray entry that only covers 16 sectors splits the free space.
    regions = compute_unallocated_regions(
        [entry(0, 2048, 2048), entry(1, 4100, 16)], 1, 10000, merge_gap_sectors=64
    )
    # The leading free region stays separate: the partition before it is
    # large.  The two regions behind the stray entry are joined.
    assert len(regions) == 2
    assert regions[0].start_sector == 1
    assert regions[1].start_sector == 4096
    assert regions[1].sector_count == 10000 - 4096


def test_free_regions_separated_by_a_large_partition_stay_split():
    regions = compute_unallocated_regions(
        [entry(0, 2048, 2048), entry(1, 4100, 2048)], 1, 10000, merge_gap_sectors=64
    )
    assert len(regions) == 3


def test_an_empty_area_yields_no_regions():
    assert compute_unallocated_regions([], 100, 100) == []
