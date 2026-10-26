"""Confirm a partition boundary by matching the NTFS allocation bitmap.

The central idea is that an NTFS volume owns a ``$Bitmap`` meta-file whose
bits mark every cluster as allocated or free.  When a partition entry is lost
the volume itself is usually intact, so the bitmap still describes the
volume exactly.

Given a candidate start sector the matcher therefore:

1. reads the ``$Bitmap`` of the volume found there;
2. determines the highest cluster that the bitmap marks as allocated;
3. verifies on the actual disk that clusters the bitmap calls *allocated*
   really contain data and clusters it calls *free* really are zeroed;
4. samples the sectors immediately *before* the candidate start to confirm
   that they are foreign to this volume, which validates the start boundary.

The ratio of clusters that agree with the bitmap becomes the confidence of the
candidate, and the highest allocated cluster determines the size of the
partition.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..device import RawDevice
from ..fs.ntfs import NtfsBootSector, NtfsVolume

logger = logging.getLogger(__name__)

__all__ = ["BitmapMatch", "analyse_bitmap", "MAX_SCAN_BYTES"]

#: Upper bound on how much of the volume is read back for verification.
MAX_SCAN_BYTES = 512 * 1024 * 1024

#: Number of clusters read per I/O batch.
_BATCH_CLUSTERS = 2048


@dataclass(frozen=True)
class BitmapMatch:
    """Outcome of a bitmap based boundary check."""

    matched: bool
    score: float
    start_sector: int
    end_sector: int
    used_clusters: int
    total_clusters: int
    verified_clusters: int
    evidence: tuple[str, ...] = ()

    @property
    def size_sectors(self) -> int:
        return max(0, self.end_sector - self.start_sector)


def _bit_is_set(bitmap: bytes, index: int) -> bool:
    byte = bitmap[index >> 3]
    return bool(byte & (1 << (index & 7)))


def find_max_used_cluster(bitmap: bytes) -> int:
    """Return the highest cluster index marked as allocated, or ``-1``."""
    for i in range(len(bitmap) - 1, -1, -1):
        if bitmap[i]:
            for bit in range(7, -1, -1):
                if bitmap[i] & (1 << bit):
                    return (i << 3) + bit
    return -1


def _count_allocated(bitmap: bytes) -> int:
    """Count the set bits of the allocation bitmap."""
    total = 0
    for byte in bitmap:
        while byte:
            byte &= byte - 1
            total += 1
    return total


def analyse_bitmap(
    ctx,
    boot: NtfsBootSector,
    max_scan_bytes: int = MAX_SCAN_BYTES,
    verify_before: bool = True,
) -> BitmapMatch | None:
    """Verify a candidate NTFS volume against its own allocation bitmap.

    ``ctx`` is a :class:`lostpart.fs.base.ProbeContext`.  Returns ``None``
    when the bitmap cannot be read at all.
    """
    volume = NtfsVolume(ctx, boot)
    try:
        bitmap = volume.read_bitmap()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("cannot read $Bitmap: %s", exc)
        return None
    if not bitmap or len(bitmap) < 8:
        return None

    cluster_size = boot.cluster_size
    total_clusters = min(
        len(bitmap) * 8,
        boot.total_sectors // boot.sectors_per_cluster,
    )
    max_used = find_max_used_cluster(bitmap[: (total_clusters + 7) // 8])
    if max_used < 0:
        return BitmapMatch(
            matched=False,
            score=0.0,
            start_sector=ctx.start_sector,
            end_sector=ctx.start_sector,
            used_clusters=0,
            total_clusters=total_clusters,
            verified_clusters=0,
            evidence=("allocation bitmap is entirely empty",),
        )

    evidence: list[str] = []
    used_clusters = _count_allocated(bitmap[: (total_clusters + 7) // 8])

    # --- verify the volume body against the bitmap ---------------------
    clusters_to_check = min(total_clusters, max_used + 1)
    byte_budget = min(max_scan_bytes, clusters_to_check * cluster_size)
    clusters_to_check = min(clusters_to_check, byte_budget // cluster_size)

    agree = 0
    checked = 0
    mismatches = 0
    cluster_index = 0
    while cluster_index < clusters_to_check:
        batch = min(_BATCH_CLUSTERS, clusters_to_check - cluster_index)
        try:
            data = ctx.device.read_at(
                ctx.byte_offset + cluster_index * cluster_size, batch * cluster_size
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("bitmap verification read failed at cluster %d: %s", cluster_index, exc)
            break
        for i in range(batch):
            idx = cluster_index + i
            chunk = data[i * cluster_size:(i + 1) * cluster_size]
            if not chunk:
                break
            nonzero = len(chunk) - chunk.count(0)
            expected_allocated = _bit_is_set(bitmap, idx)
            if expected_allocated:
                ok = nonzero > 0
            else:
                ok = nonzero == 0
            checked += 1
            if ok:
                agree += 1
            else:
                mismatches += 1
        cluster_index += batch

    score = (agree / checked) if checked else 0.0
    evidence.append(
        f"{agree}/{checked} clusters agree with the allocation bitmap "
        f"({mismatches} mismatches)"
    )
    evidence.append(f"highest allocated cluster is {max_used} of {total_clusters}")

    # --- validate the start boundary -----------------------------------
    before_ok = True
    if verify_before and ctx.start_sector > 0:
        probe_clusters = min(8, max(1, ctx.start_sector // 8))
        offset = ctx.byte_offset - probe_clusters * cluster_size
        if offset >= 0:
            try:
                data = ctx.device.read_at(offset, probe_clusters * cluster_size)
                nonzero = len(data) - data.count(0)
                before_ok = nonzero == 0
            except Exception:  # pragma: no cover - defensive
                before_ok = False
            if before_ok:
                evidence.append("the sectors preceding the candidate start are empty")
            else:
                evidence.append("the sectors preceding the candidate start contain data")
                score *= 0.8
        else:
            # There is nothing before the candidate to look at, so the start
            # boundary stays unproven -- it is not evidence for the volume.
            evidence.append("there are no sectors before the candidate to check")

    # --- the volume must end where the bitmap stops ---------------------
    end_cluster = max_used + 1
    end_sector = ctx.start_sector + end_cluster * cluster_size // ctx.sector_size

    matched = score >= 0.85 and checked > 0
    return BitmapMatch(
        matched=matched,
        score=round(score, 4),
        start_sector=ctx.start_sector,
        end_sector=end_sector,
        used_clusters=used_clusters,
        total_clusters=total_clusters,
        verified_clusters=checked,
        evidence=tuple(evidence),
    )
