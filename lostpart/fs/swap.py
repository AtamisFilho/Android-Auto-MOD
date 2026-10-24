"""Linux swap probe.

The on-disk structures implemented here are described by the Linux kernel
documentation ``Documentation/admin-guide/uses-of-swapon`` and by the kernel
header ``include/linux/swap.h``.

The kernel keeps a ``struct swap_header_s`` (68 bytes) at the very end of the
first 4096 byte page of a swap area, so the header starts at byte 4028 and
the magic is the ``u32`` at byte 4028.  Some tools historically wrote the
ten byte ASCII signature ``SWAPSPACE2`` at the end of the first page (byte
4086) instead; both locations are checked.

Byte order note: the magic is verified against the *raw bytes* first (the
ASCII signature) and only then against the numeric constants, so the check
never depends on an ambiguous byte order.
"""

from __future__ import annotations

import logging
import struct
import uuid as uuid_module
from dataclasses import dataclass
from typing import Final

from ..constants import (
    SWAP_HEADER_OFFSET,
    SWAP_HEADER_SIZE,
    SWAP_MAGIC_1,
    SWAP_MAGIC_2,
    SWAP_MAGIC_ALT_OFFSET,
    SWAP_MAGIC_OFFSET,
    SWAP_OFF_FLAGS,
    SWAP_OFF_LAST_PAGE,
    SWAP_OFF_MAGIC,
    SWAP_OFF_NR_CLUSTERS,
    SWAP_OFF_PAGE_SIZE,
    SWAP_OFF_UUID,
    SWAP_OFF_VERSION,
    SWAP_OFF_VOLUME_LABEL,
    SWAP_SIGNATURE,
    SWAP_VERSION_1,
    SWAP_VERSION_2,
)
from .base import DirEntry, ProbeContext, ProbeResult

logger = logging.getLogger(__name__)

#: Identifier reported by the registry for this module.
FS_TYPE: Final = "swap"

#: Size of the first page of a swap area.
SWAP_PAGE_SIZE: Final = 4096
#: Signature of the old ``SWAP-SPACE`` layout (swap version 0/1).
SWAP_SIGNATURE_LEGACY: Final = b"SWAP-SPACE"
#: Four byte prefix shared by both ASCII signatures.
SWAP_SIGNATURE_PREFIX: Final = b"SWAP"
#: Magic value seen when the ``SWAP`` signature is stored byte swapped.
SWAP_MAGIC_SWAPPED: Final = 0x73776153
#: Numeric magics accepted next to the ASCII signatures.
SWAP_MAGIC_VALUES: Final = frozenset(
    {SWAP_MAGIC_1, SWAP_MAGIC_2, SWAP_MAGIC_SWAPPED}
)
#: Length of the ``volume_label`` and ``uuid`` fields.
SWAP_LABEL_SIZE: Final = 16
SWAP_UUID_SIZE: Final = 16


def _u32(buf: bytes, off: int) -> int | None:
    """Return the little endian ``u32`` at ``off`` or ``None`` if truncated."""
    if off < 0 or off + 4 > len(buf):
        return None
    return struct.unpack_from("<I", buf, off)[0]


def _magic_form(page: bytes, offset: int) -> str | None:
    """Describe the swap magic found at ``offset`` of ``page``.

    Returns ``None`` when no known magic is present.  The raw bytes are
    compared with the ASCII signatures first; the numeric constants are then
    accepted in both byte orders so that the check is unambiguous.
    """
    chunk = page[offset : offset + len(SWAP_SIGNATURE)]
    if len(chunk) < 4:
        return None
    if chunk.startswith(SWAP_SIGNATURE):
        return "SWAPSPACE2 signature"
    if chunk.startswith(SWAP_SIGNATURE_LEGACY):
        return "SWAP-SPACE signature"
    little = struct.unpack_from("<I", chunk, 0)[0]
    big = struct.unpack_from(">I", chunk, 0)[0]
    if little in SWAP_MAGIC_VALUES:
        return f"magic 0x{little:08X} (little endian)"
    if big in SWAP_MAGIC_VALUES:
        return f"magic 0x{big:08X} (big endian)"
    if chunk[:4] == SWAP_SIGNATURE_PREFIX:
        return "SWAP signature"
    return None


def _printable(raw: bytes) -> str:
    """Decode a fixed size text field, or return an empty string."""
    if not raw:
        return ""
    text = raw.split(b"\x00", 1)[0]
    if not text:
        return ""
    try:
        decoded = text.decode("ascii")
    except UnicodeDecodeError:
        return ""
    if not decoded.isprintable():
        return ""
    return decoded.strip()


@dataclass(frozen=True)
class _SwapHeader:
    """The parsed ``struct swap_header_s`` of a swap area."""

    magic_form: str
    offset: int
    version: int | None
    last_page: int | None
    nr_clusters: int | None
    page_size: int | None
    flags: int | None
    volume_label: str
    uuid: str


def _parse_header(page: bytes, offset: int) -> _SwapHeader | None:
    """Parse the swap header that starts at ``offset`` of ``page``."""
    form = _magic_form(page, offset)
    if form is None:
        return None

    version = _u32(page, offset + SWAP_OFF_VERSION)
    last_page = _u32(page, offset + SWAP_OFF_LAST_PAGE)
    nr_clusters = _u32(page, offset + SWAP_OFF_NR_CLUSTERS)
    page_size = _u32(page, offset + SWAP_OFF_PAGE_SIZE)
    flags = _u32(page, offset + SWAP_OFF_FLAGS)
    if version is None or last_page is None or nr_clusters is None:
        return None

    label = _printable(
        page[offset + SWAP_OFF_VOLUME_LABEL : offset + SWAP_OFF_VOLUME_LABEL + SWAP_LABEL_SIZE]
    )
    raw_uuid = page[offset + SWAP_OFF_UUID : offset + SWAP_OFF_UUID + SWAP_UUID_SIZE]
    uuid_text = ""
    if len(raw_uuid) == SWAP_UUID_SIZE and any(raw_uuid):
        uuid_text = str(uuid_module.UUID(bytes=bytes(raw_uuid)))

    return _SwapHeader(
        magic_form=form,
        offset=offset,
        version=version,
        last_page=last_page,
        nr_clusters=nr_clusters,
        page_size=page_size,
        flags=flags,
        volume_label=label,
        uuid=uuid_text,
    )


def detect(ctx: ProbeContext) -> ProbeResult | None:
    """Detect a Linux swap area at the start of a volume.

    The first 4096 bytes of the candidate are read and the
    ``struct swap_header_s`` at ``SWAP_MAGIC_OFFSET`` (4028) is parsed.  The
    magic is accepted as the ASCII signature ``SWAPSPACE2`` (or the legacy
    ``SWAP-SPACE``), as the raw ``SWAP`` prefix, or as the numeric
    ``SWAP_MAGIC_1`` / ``SWAP_MAGIC_2`` value in either byte order.

    The confidence ladder is:

    ================================================  =======
    Evidence                                          Weight
    ================================================  =======
    magic found at ``SWAP_MAGIC_OFFSET`` (4028)       +0.70
    magic found at ``SWAP_MAGIC_ALT_OFFSET`` (4086)  +0.55
    version field is 1                               +0.30
    version field unreadable (ASCII signature)       +0.25
    printable volume label                           +0.05
    ================================================  =======

    The result is capped at 1.0; an unexpected version lowers the score to
    0.7 / 0.6.  ``None`` is returned when no known magic is present.
    """
    try:
        page = ctx.read(0, SWAP_PAGE_SIZE)
    except Exception:  # pragma: no cover - device error
        logger.debug("swap: cannot read the first page", exc_info=True)
        return None
    if len(page) < SWAP_HEADER_OFFSET + SWAP_HEADER_SIZE:
        page = page.ljust(SWAP_HEADER_OFFSET + SWAP_HEADER_SIZE, b"\x00")

    header = _parse_header(page, SWAP_MAGIC_OFFSET)
    alt_header: _SwapHeader | None = None
    if header is None:
        alt_header = _parse_header(page, SWAP_MAGIC_ALT_OFFSET)
        if alt_header is None:
            return None
        header = alt_header

    evidence: list[str] = []
    if alt_header is None:
        evidence.append(
            f"swap header magic ({header.magic_form}) at offset {SWAP_MAGIC_OFFSET}"
        )
        confidence = 0.70
    else:
        evidence.append(
            f"swap header magic ({header.magic_form}) at alternative offset "
            f"{SWAP_MAGIC_ALT_OFFSET}"
        )
        confidence = 0.55

    # The ASCII signature is written over the whole header struct, so the
    # version field is not meaningful in that case.
    signature_form = header.magic_form.endswith("signature")
    if signature_form:
        evidence.append(
            "version field is covered by the ASCII signature and cannot be read"
        )
        confidence += 0.25
    elif header.version == SWAP_VERSION_1:
        evidence.append("swap header version 1")
        confidence += 0.30
    else:
        evidence.append(f"unexpected swap header version {header.version}")
        confidence = min(confidence + 0.10, 0.70)

    if header.volume_label:
        evidence.append(f"swap volume label {header.volume_label!r}")
        confidence += 0.05
    if header.uuid:
        evidence.append(f"swap uuid {header.uuid}")

    confidence = min(confidence, 1.0)

    version = header.version if not signature_form else None
    details: dict[str, object] = {
        "version": version,
        "magic": header.magic_form,
        "magic_offset": header.offset,
        "page_size": header.page_size if version == SWAP_VERSION_1 else None,
        "flags": header.flags,
        "volume_label": header.volume_label,
        "uuid": header.uuid,
        "bytes_per_sector": ctx.sector_size,
    }
    # ``last_page`` and ``nr_clusters`` only exist in the version 2 layout;
    # in version 1 they are padding and must not be reported as a size.
    if version == SWAP_VERSION_2:
        details["last_page"] = header.last_page
        details["nr_clusters"] = header.nr_clusters
        if header.nr_clusters and header.page_size:
            total_bytes = header.nr_clusters * header.page_size
            details["total_sectors"] = total_bytes // ctx.sector_size
    else:
        details["last_page"] = None
        details["nr_clusters"] = None

    label = header.volume_label or "Linux swap"
    return ProbeResult(
        fs_type=FS_TYPE,
        label=label,
        confidence=confidence,
        details=details,
        evidence=tuple(evidence),
    )


def read_directory(ctx: ProbeContext, path: tuple[str, ...] = ()) -> list[DirEntry]:
    """A swap area has no directory tree, so this always returns ``[]``.

    Linux swap areas are a flat array of pages; they contain no directories,
    no inodes and no file names.  The function therefore never raises and
    always returns an empty list -- the swap probe exists to recognise the
    volume and to report its geometry, not to browse its content.
    """
    return []
