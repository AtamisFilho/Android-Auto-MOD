"""Registry of the filesystem probes.

The registry collects every filesystem module that is available, dispatches a
candidate start sector to all of them and returns the best verdict.  A module
that fails to import is skipped, so a partially installed package still works
for the filesystems that are present.
"""

from __future__ import annotations

import importlib
import logging
from types import ModuleType

from .base import DirEntry, ProbeContext, ProbeResult

logger = logging.getLogger(__name__)

__all__ = ["MODULES", "detect_all", "detect_best", "read_directory", "available_types"]

#: Names of the filesystem modules, in the order they are probed.
_MODULE_NAMES = ("ntfs", "exfat", "fat", "ext", "swap", "hfsplus")


def _load(name: str) -> ModuleType | None:
    try:
        return importlib.import_module(f"{__package__}.{name}")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("filesystem module %s is unavailable: %s", name, exc)
        return None


#: The loaded filesystem modules.
MODULES: list[ModuleType] = [
    module for module in (_load(name) for name in _MODULE_NAMES) if module is not None
]


def available_types() -> list[str]:
    """The filesystem types that can be detected."""
    return [getattr(module, "FS_TYPE", module.__name__) for module in MODULES]


def detect_all(ctx: ProbeContext) -> list[ProbeResult]:
    """Run every probe against a candidate start and return all verdicts."""
    results: list[ProbeResult] = []
    for module in MODULES:
        detect = getattr(module, "detect", None)
        if detect is None:
            continue
        try:
            result = detect(ctx)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("probe %s failed: %s", module.__name__, exc)
            continue
        if result is not None:
            results.append(result)
    return results


def detect_best(ctx: ProbeContext) -> ProbeResult | None:
    """Return the verdict with the highest confidence."""
    results = detect_all(ctx)
    if not results:
        return None
    return max(results, key=lambda r: r.confidence)


def read_directory(ctx: ProbeContext, path: tuple[str, ...] = ()) -> list[DirEntry]:
    """List a directory using the reader of the filesystem found at ``ctx``.

    The first module that returns entries wins.  Modules that do not
    implement browsing return an empty list, which is indistinguishable from
    an empty directory; the caller can therefore combine this with the probe
    result to know which filesystem was used.
    """
    for module in MODULES:
        reader = getattr(module, "read_directory", None)
        if reader is None:
            continue
        try:
            entries = reader(ctx, path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("reader %s failed: %s", module.__name__, exc)
            continue
        if entries:
            return entries
    return []
