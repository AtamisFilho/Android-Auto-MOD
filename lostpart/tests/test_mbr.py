"""Tests for the MBR parser and builder."""

from __future__ import annotations

from lostpart.tables.mbr import (
    build_mbr_sector,
    chs_to_lba,
    find_free_primary_slot,
    lba_to_chs,
    parse_logical_partitions,
    parse_mbr,
)

from .fixtures import mbr_entry, make_mbr


def test_parse_mbr_reads_the_four_primary_entries():
    sector = make_mbr([
        mbr_entry(2048, 1048576, 0x07),
        mbr_entry(0, 0, 0x00),
        mbr_entry(4096, 2097152, 0x83),
        mbr_entry(0, 0, 0x00),
    ])
    mbr = parse_mbr(sector)
    assert mbr.signature_valid
    assert len(mbr.entries) == 4
    first = mbr.entries[0]
    assert first.start_lba == 2048
    assert first.sector_count == 1048576
    assert first.type_byte == 0x07
    assert first.label == "NTFS / exFAT / HPFS"
    assert not first.is_empty
    assert first.end_lba == 2048 + 1048576
    assert mbr.entries[1].is_empty
    assert mbr.entries[2].type_byte == 0x83


def test_parse_mbr_detects_a_missing_boot_signature():
    sector = bytearray(make_mbr([mbr_entry(2048, 100, 0x07)]))
    sector[0x1FE] = 0x00
    mbr = parse_mbr(bytes(sector))
    assert not mbr.signature_valid


def test_build_mbr_sector_round_trips():
    entries = list(parse_mbr(make_mbr([mbr_entry(2048, 100, 0x07)])).entries)
    entries[0] = entries[0].__class__(
        index=0, boot_indicator=0x80, start_lba=2048, sector_count=100,
        type_byte=0x07, start_head=0x21, start_sector=0x08, start_cylinder=0x00,
        end_head=0xFE, end_sector=0xFF, end_cylinder=0xFF,
    )
    rebuilt = parse_mbr(build_mbr_sector(entries))
    assert rebuilt.signature_valid
    assert rebuilt.entries[0].start_lba == 2048
    assert rebuilt.entries[0].sector_count == 100
    assert rebuilt.entries[0].is_active
    assert rebuilt.entries[0].type_byte == 0x07


def test_chs_conversion_round_trips_inside_the_legacy_geometry():
    for lba in (0, 1, 63, 64, 2048, 100_000, 16_252_319):
        head, sector, cylinder = lba_to_chs(lba)
        assert chs_to_lba(head, sector, cylinder) == lba


def test_chs_conversion_flags_lba_beyond_the_legacy_geometry():
    # 1024 cylinders * 255 heads * 63 sectors per track.
    assert lba_to_chs(16_450_560) == (0xFE, 0xFF, 0xFF)


def test_find_free_primary_slot():
    mbr = parse_mbr(make_mbr([
        mbr_entry(2048, 100, 0x07),
        mbr_entry(0, 0, 0x00),
        mbr_entry(4096, 100, 0x83),
    ]))
    assert find_free_primary_slot(mbr.entries) == 1


def test_parse_logical_partitions_walks_the_ebr_chain():
    # An extended container at LBA 4096 holding one logical partition.
    primary = make_mbr([
        mbr_entry(4096, 2048, 0x05),
        mbr_entry(0, 0, 0x00),
        mbr_entry(0, 0, 0x00),
        mbr_entry(0, 0, 0x00),
    ])
    ebr = make_mbr([
        mbr_entry(4097, 1024, 0x83),
        mbr_entry(0, 0, 0x00),
    ])
    sectors = {0: primary, 4096: ebr}

    def read_sector(lba: int) -> bytes:
        return sectors[lba]

    extended = parse_mbr(primary).extended_entry()
    assert extended is not None
    logical = parse_logical_partitions(read_sector, extended)
    assert len(logical) == 1
    assert logical[0].start_lba == 4097
    assert logical[0].sector_count == 1024
    assert logical[0].index == 4
