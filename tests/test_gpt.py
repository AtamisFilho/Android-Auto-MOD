"""Tests for the GPT parser, builder and integrity checks."""

from __future__ import annotations

import struct

from lostpart.tables.gpt import (
    build_gpt_header,
    build_gpt_entry,
    build_protective_mbr,
    bytes_to_guid,
    crc32,
    guid_to_bytes,
    parse_gpt_entries,
    parse_gpt_header,
    verify_gpt_header_crc,
)
from lostpart.tables.table import detect_table_type, load_partition_table

from .fixtures import FakeDevice, make_gpt_disk

TYPE_NTFS = "{EBD0A0A2-B9E5-4433-87C0-68B6B72699C7}"
UNIQUE_1 = "{11111111-1111-1111-1111-111111111111}"
UNIQUE_2 = "{22222222-2222-2222-2222-222222222222}"


def test_guid_encoding_round_trips():
    assert bytes_to_guid(guid_to_bytes(TYPE_NTFS)) == TYPE_NTFS


def test_crc32_matches_the_reference_value():
    assert crc32(b"123456789") == 0xCBF43926


def test_protective_mbr_claims_the_whole_disk():
    sector = build_protective_mbr(1000)
    assert sector[0x1FE:0x200] == b"\x55\xaa"
    entry = sector[0x1BE:0x1BE + 16]
    type_byte = entry[4]
    start_lba, count = struct.unpack_from("<II", entry, 8)
    assert type_byte == 0xEE
    assert start_lba == 1
    assert count == 999


def test_build_gpt_header_computes_a_valid_crc():
    header = build_gpt_header(
        current_lba=1, backup_lba=100, first_usable_lba=34, last_usable_lba=67,
        disk_guid=UNIQUE_1, partition_entry_lba=2, partition_entry_count=128,
        partition_entry_size=128, partition_entry_array_crc32=0,
    )
    assert header[:8] == b"EFI PART"
    assert verify_gpt_header_crc(header)
    parsed = parse_gpt_header(header)
    assert parsed is not None
    assert parsed.current_lba == 1
    assert parsed.backup_lba == 100
    assert parsed.disk_guid == UNIQUE_1


def test_parse_gpt_header_rejects_a_wrong_signature():
    header = bytearray(build_gpt_header(
        current_lba=1, backup_lba=100, first_usable_lba=34, last_usable_lba=67,
        disk_guid=UNIQUE_1, partition_entry_lba=2, partition_entry_count=128,
        partition_entry_size=128, partition_entry_array_crc32=0,
    ))
    header[0:8] = b"NOTGPT!"
    assert parse_gpt_header(bytes(header)) is None


def test_load_partition_table_reads_a_gpt_disk():
    disk = make_gpt_disk(
        total_sectors=2048,
        entries=[(TYPE_NTFS, UNIQUE_1, 34, "System")],
    )
    device = FakeDevice(disk)
    assert detect_table_type(device) == "gpt"
    table = load_partition_table(device)
    assert table is not None
    assert table.kind == "gpt"
    assert table.header_crc_valid
    assert table.entry_array_crc_valid
    assert len(table.occupied) == 1
    entry = table.occupied[0]
    assert entry.start_lba == 34
    assert entry.sector_count == 2
    assert entry.unique_guid == UNIQUE_1


def test_gpt_entry_round_trips():
    entry = build_gpt_entry(
        index=3, type_guid=TYPE_NTFS, unique_guid=UNIQUE_2,
        first_lba=100, last_lba=199, attributes=0, name="Dados",
    )
    raw = entry.to_bytes()
    assert len(raw) == 128
    parsed = parse_gpt_entries(raw, 1)[0]
    assert parsed.type_guid == TYPE_NTFS
    assert parsed.unique_guid == UNIQUE_2
    assert parsed.first_lba == 100
    assert parsed.last_lba == 199
    assert parsed.sector_count == 100
    assert parsed.name == "Dados"


def test_a_gpt_disk_is_detected_before_the_protective_mbr():
    # The protective MBR alone must not make the disk look like a plain MBR.
    disk = make_gpt_disk(total_sectors=2048)
    device = FakeDevice(disk)
    assert detect_table_type(device) == "gpt"
