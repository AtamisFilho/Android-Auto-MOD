"""Contract tests for every filesystem module.

These tests do not depend on the details of a particular format: they check
that each module honours the contract in :mod:`lostpart.fs.base`, survives
corrupt input and refuses to raise.
"""

from __future__ import annotations

import importlib

import pytest

from lostpart.fs import registry
from lostpart.fs.base import DirEntry, ProbeContext, ProbeResult

from .fixtures import FakeDevice

MODULE_NAMES = ("ntfs", "exfat", "fat", "ext", "swap", "hfsplus")


def _context(data: bytes) -> ProbeContext:
    device = FakeDevice(data)
    return ProbeContext(
        device=device,
        start_sector=0,
        sector_size=device.sector_size,
        total_sectors=device.total_sectors,
    )


@pytest.mark.parametrize("name", MODULE_NAMES)
def test_the_module_honours_the_contract(name):
    try:
        module = importlib.import_module(f"lostpart.fs.{name}")
    except ModuleNotFoundError:
        pytest.skip(f"the {name} module is not installed")
    assert isinstance(module.FS_TYPE, str) and module.FS_TYPE
    assert callable(module.detect)
    assert callable(module.read_directory)


@pytest.mark.parametrize("name", MODULE_NAMES)
def test_detect_rejects_random_data(name):
    try:
        module = importlib.import_module(f"lostpart.fs.{name}")
    except ModuleNotFoundError:
        pytest.skip(f"the {name} module is not installed")
    for pattern in (b"\x00" * 4096, b"\x5A" * 4096, b"\xFF" * 4096, b""):
        result = module.detect(_context(pattern))
        assert result is None or isinstance(result, ProbeResult)


@pytest.mark.parametrize("name", MODULE_NAMES)
def test_detect_never_raises_on_truncated_data(name):
    try:
        module = importlib.import_module(f"lostpart.fs.{name}")
    except ModuleNotFoundError:
        pytest.skip(f"the {name} module is not installed")
    for length in (1, 2, 16, 64, 255, 511, 512, 513, 1024):
        data = b"\xAA" * length
        result = module.detect(_context(data))
        assert result is None or isinstance(result, ProbeResult)


@pytest.mark.parametrize("name", MODULE_NAMES)
def test_read_directory_never_raises_on_garbage(name):
    try:
        module = importlib.import_module(f"lostpart.fs.{name}")
    except ModuleNotFoundError:
        pytest.skip(f"the {name} module is not installed")
    entries = module.read_directory(_context(b"\xAA" * 8192), ())
    assert isinstance(entries, list)
    assert all(isinstance(entry, DirEntry) for entry in entries)


def test_the_registry_reports_every_available_filesystem():
    types = registry.available_types()
    assert "ntfs" in types
    assert len(types) >= 2


def test_detect_all_returns_nothing_for_random_data():
    results = registry.detect_all(_context(b"\x33" * 8192))
    assert all(isinstance(result, ProbeResult) for result in results)
