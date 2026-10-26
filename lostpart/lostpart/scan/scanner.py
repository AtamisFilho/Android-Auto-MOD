"""Scan a disk for filesystems that have no partition entry.

The scan never walks the whole disk blindly.  It first computes the free
regions of the disk (the gaps between the known partitions) and then looks
for filesystem signatures inside those regions only.  Signatures are found by
searching large blocks of data for the well known byte patterns, which is far
faster than reading every sector one at a time.

Every signature hit is then handed to the filesystem probes, which validate
the structure properly.  For NTFS the allocation bitmap of the volume is used
to confirm both the size and the start of the partition, which is what turns
a "there is a boot sector here" hint into a reliable recovery candidate.
"""

from __future__ import annotations

import logging
import struct
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from ..constants import (
    EXFAT_OEM_ID,
    EXFAT_OFF_OEM,
    EXT_SUPERBLOCK_MAGIC,
    EXT_SUPERBLOCK_OFFSET,
    FAT32_SIGNATURE,
    FAT16_OFF_FS_TYPE,
    FAT_OFF_FS_TYPE,
    HFSPLUS_SIGNATURE,
    HFSPLUS_SIGNATURE_OFFSET,
    NTFS_OEM_ID,
    NTFS_OFF_OEM,
    SWAP_MAGIC_ALT_OFFSET,
    SWAP_MAGIC_OFFSET,
    SWAP_SIGNATURE,
)
from ..device import RawDevice
from ..fs.base import ProbeContext
from ..fs import registry
from ..fs.ntfs import parse_boot_sector
from .bitmap_match import analyse_bitmap
from .model import LostPartitionCandidate, ScanResult
from .unallocated import UnallocatedRegion, compute_unallocated_regions

logger = logging.getLogger(__name__)

__all__ = ["Scanner", "SCAN_MODE_QUICK", "SCAN_MODE_FULL", "SIGNATURES"]

SCAN_MODE_QUICK = "quick"
SCAN_MODE_FULL = "full"

#: Default block size used when reading the disk during a scan.
DEFAULT_CHUNK_BYTES = 16 * 1024 * 1024

#: Number of bytes shared between two consecutive blocks so that a signature
#: split across the boundary is still found.
_OVERLAP_BYTES = 8192


@dataclass(frozen=True)
class _Signature:
    """A byte pattern that hints at the start of a filesystem."""

    fs_type: str
    pattern: bytes
    #: Offset of the pattern inside the boot sector.
    offset: int
    #: Minimum alignment of the candidate start, in sectors.
    alignment: int = 1


#: Signatures searched for during a scan.  Every hit is validated by the
#: corresponding probe, so false positives are cheap to reject.
SIGNATURES: tuple[_Signature, ...] = (
    _Signature("ntfs", NTFS_OEM_ID, NTFS_OFF_OEM),
    _Signature("exfat", EXFAT_OEM_ID, EXFAT_OFF_OEM),
    _Signature("fat", FAT32_SIGNATURE, FAT_OFF_FS_TYPE),
    _Signature("fat", b"FAT16   ", FAT16_OFF_FS_TYPE),
    _Signature("fat", b"FAT12   ", FAT16_OFF_FS_TYPE),
    _Signature("ext", struct.pack("<H", EXT_SUPERBLOCK_MAGIC), EXT_SUPERBLOCK_OFFSET),
    _Signature("swap", SWAP_SIGNATURE, SWAP_MAGIC_OFFSET),
    _Signature("swap", SWAP_SIGNATURE, SWAP_MAGIC_ALT_OFFSET),
    _Signature("hfsplus", HFSPLUS_SIGNATURE, HFSPLUS_SIGNATURE_OFFSET),
)


class Scanner:
    """Find lost partitions inside the free space of a disk."""

    def __init__(
        self,
        device: RawDevice,
        mode: str = SCAN_MODE_FULL,
        min_confidence: float = 0.35,
        chunk_bytes: int = DEFAULT_CHUNK_BYTES,
        verify_ntfs_bitmap: bool = True,
    ) -> None:
        self.device = device
        self.mode = mode
        self.min_confidence = min_confidence
        self.chunk_bytes = chunk_bytes
        self.verify_ntfs_bitmap = verify_ntfs_bitmap

    # -- helpers ---------------------------------------------------------
    def _context(self, sector: int) -> ProbeContext:
        return ProbeContext(
            device=self.device,
            start_sector=sector,
            sector_size=self.device.sector_size,
            total_sectors=self.device.total_sectors,
        )

    def _hits_in_block(self, block: bytes, block_start_sector: int) -> set[int]:
        """Return the candidate start sectors found inside a block of data."""
        sector_size = self.device.sector_size or 512
        hits: set[int] = set()
        for signature in SIGNATURES:
            position = block.find(signature.pattern)
            while position >= 0:
                byte_offset = position - signature.offset
                if byte_offset >= 0 and byte_offset % sector_size == 0:
                    hits.add(block_start_sector + byte_offset // sector_size)
                position = block.find(signature.pattern, position + 1)
        return hits

    # -- main entry point ------------------------------------------------
    def scan(
        self,
        regions: Iterable[UnallocatedRegion],
        progress: Callable[[float, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[LostPartitionCandidate]:
        """Scan the given free regions and return the candidates found."""
        found: dict[int, LostPartitionCandidate] = {}
        regions = list(regions)
        total_bytes = sum(r.sector_count for r in regions) * (self.device.sector_size or 512)
        scanned = 0

        for region in regions:
            if should_cancel and should_cancel():
                break
            region_bytes = region.sector_count * (self.device.sector_size or 512)
            block_size = self.chunk_bytes
            if self.mode == SCAN_MODE_QUICK:
                block_size = 1024 * 1024
            offset = region.start_sector * (self.device.sector_size or 512)
            end = offset + region_bytes

            while offset < end:
                if should_cancel and should_cancel():
                    break
                read_size = min(block_size, end - offset)
                try:
                    block = self.device.read_at(offset, read_size)
                except Exception as exc:
                    logger.debug("read failed at offset %d: %s", offset, exc)
                    offset += read_size
                    continue
                block_start_sector = offset // (self.device.sector_size or 512)
                for sector in sorted(self._hits_in_block(block, block_start_sector)):
                    if sector in found:
                        continue
                    if not (region.start_sector <= sector < region.end_sector):
                        continue
                    candidate = self._evaluate(sector)
                    if candidate is not None:
                        found[sector] = candidate
                scanned += len(block)
                offset += read_size
                if progress and total_bytes:
                    progress(min(1.0, scanned / total_bytes), f"scanning sector {offset // (self.device.sector_size or 512)}")

        return self._resolve_overlaps(sorted(found.values(), key=lambda c: c.start_sector))

    # -- candidate evaluation -------------------------------------------
    def _evaluate(self, sector: int) -> LostPartitionCandidate | None:
        """Validate a candidate start sector and build a candidate record."""
        ctx = self._context(sector)
        results = registry.detect_all(ctx)
        if not results:
            return None
        best = max(results, key=lambda r: r.confidence)
        if best.confidence < self.min_confidence:
            return None

        candidate = LostPartitionCandidate(
            start_sector=sector,
            sector_count=best.size_sectors or 0,
            fs_type=best.fs_type,
            label=best.label,
            confidence=best.confidence,
            source="boot sector",
            evidence=best.evidence,
            details=dict(best.details),
            volume_name=str(best.details.get("volume_label", "") or ""),
            sector_size=self.device.sector_size or 512,
        )

        if best.fs_type == "ntfs" and self.verify_ntfs_bitmap:
            self._refine_with_bitmap(candidate, ctx)
        return candidate

    def _refine_with_bitmap(self, candidate: LostPartitionCandidate, ctx: ProbeContext) -> None:
        """Use the NTFS allocation bitmap to confirm size and start."""
        try:
            boot = parse_boot_sector(ctx.read(0, 512))
        except Exception:  # pragma: no cover - defensive
            return
        if boot is None:
            return
        match = analyse_bitmap(ctx, boot)
        if match is None:
            candidate.evidence = candidate.evidence + ("the $Bitmap could not be read",)
            candidate.confidence *= 0.8
            return

        candidate.evidence = candidate.evidence + match.evidence
        if match.matched:
            candidate.confidence = min(1.0, max(candidate.confidence, 0.6 + 0.4 * match.score))
            candidate.source = "boot sector + allocation bitmap"
        else:
            candidate.confidence *= 0.7
            candidate.evidence = candidate.evidence + (
                "the allocation bitmap does not match the data on disk",
            )
        if match.end_sector > candidate.start_sector:
            candidate.sector_count = match.end_sector - candidate.start_sector
        candidate.details["bitmap_score"] = match.score
        candidate.details["bitmap_used_clusters"] = match.used_clusters

    # -- post processing --------------------------------------------------
    def _resolve_overlaps(
        self, candidates: list[LostPartitionCandidate]
    ) -> list[LostPartitionCandidate]:
        """Drop candidates that overlap a more confident one.

        Two filesystems cannot occupy the same sectors.  When two candidates
        overlap, the one with the higher confidence wins; on a tie the one
        with more sectors wins.
        """
        resolved: list[LostPartitionCandidate] = []
        for candidate in sorted(
            candidates, key=lambda c: (-c.confidence, -c.sector_count, c.start_sector)
        ):
            clash = False
            for kept in resolved:
                if candidate.start_sector < kept.end_sector and kept.start_sector < candidate.end_sector:
                    clash = True
                    break
            if not clash:
                resolved.append(candidate)
        resolved.sort(key=lambda c: c.start_sector)
        return resolved


def scan_disk(
    device: RawDevice,
    table: "object",
    mode: str = SCAN_MODE_FULL,
    progress: Callable[[float, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ScanResult:
    """Convenience wrapper: compute the free regions of a disk and scan them."""
    from ..tables.table import TABLE_TYPE_GPT, PartitionTable

    assert isinstance(table, PartitionTable)
    sector_size = device.sector_size or 512
    if table.kind == TABLE_TYPE_GPT and table.gpt_header is not None:
        area_start = table.gpt_header.first_usable_lba
        area_end = table.gpt_header.last_usable_lba + 1
    else:
        area_start = 1
        area_end = device.total_sectors

    regions = compute_unallocated_regions(table.entries, area_start, area_end)
    scanner = Scanner(device, mode=mode)
    started = time.monotonic()
    candidates = scanner.scan(regions, progress=progress, should_cancel=should_cancel)
    elapsed = time.monotonic() - started
    return ScanResult(
        device="",
        table_type=table.kind,
        mode=mode,
        candidates=candidates,
        regions=regions,
        elapsed_seconds=elapsed,
        bytes_scanned=sum(r.sector_count for r in regions) * sector_size,
        cancelled=bool(should_cancel and should_cancel()),
    )
