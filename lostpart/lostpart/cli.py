"""Command line interface of :mod:`lostpart`.

Commands::

    lostpart list                      list the disks and their partition tables
    lostpart scan    --device N        look for lost partitions in the free space
    lostpart recover --device N ...    write the missing partition entry back
    lostpart browse  --device N ...    list the files of a recovered partition
    lostpart backup  --device N        save the partition table structures
    lostpart restore --device N        restore a saved partition table

Started without a command the tool opens an interactive menu, so a double
click on the executable does something useful instead of closing at once.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

from . import __version__
from .browse.lister import list_partition, mount_partition
from .device import open_device
from .errors import LostPartError
from .recover.backup import create_backup, load_backup, restore_backup
from .recover.writer import recover_partition
from .scan.checkpoint import STATUS_CANCELLED, STATUS_DONE, ScanCheckpoint
from .scan.model import LostPartitionCandidate
from .scan.scanner import SCAN_MODE_FULL, SCAN_MODE_QUICK, Scanner, scan_disk
from .tables.table import TABLE_TYPE_GPT, load_partition_table

__all__ = ["main", "build_parser"]

logger = logging.getLogger("lostpart")


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(value) < 1024.0 or unit == "PiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.1f} PiB"


def _print_table(rows: list[list[str]], headers: list[str]) -> None:
    if not rows:
        print("(none)")
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def _capture(function, *args, **kwargs) -> str:
    """Run a printing function and return everything it printed."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        function(*args, **kwargs)
    return buffer.getvalue()


def io_table(rows: list[list[str]]) -> str:
    """Render a table the same way :func:`_print_table` does, as text."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _print_table(rows, ["#", "start", "sectors", "size", "type", "boot", "kind"])
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Core operations, shared by the command line and the interactive menu
# --------------------------------------------------------------------------


def list_devices_text(device_spec: str | None = None) -> str:
    """Return the listing of the disks and their partition tables."""
    from .device import list_physical_devices

    if device_spec:
        devices = [open_device(device_spec, read_only=True)]
    else:
        devices = list_physical_devices()

    if not devices:
        return "no physical disk could be opened (are you running elevated?)"

    chunks: list[str] = []
    for device in devices:
        try:
            table = load_partition_table(device)
        except LostPartError as exc:
            chunks.append(f"{device.path}: {exc}")
            continue
        lines = [f"=== {device.path} ==="]
        lines.append(
            f"size    : {device.size} bytes ({device.total_sectors} sectors "
            f"of {device.sector_size} bytes)"
        )
        if table is None:
            lines.append("table   : none")
            chunks.append("\n".join(lines))
            continue
        lines.append(f"table   : {table.kind.upper()}")
        if table.kind == TABLE_TYPE_GPT and table.gpt_header is not None:
            header = table.gpt_header
            lines.append(f"disk GUID: {header.disk_guid}")
            lines.append(
                f"header CRC valid: {table.header_crc_valid}, "
                f"entry array CRC valid: {table.entry_array_crc_valid}"
            )
        rows = []
        for entry in table.sorted_by_start():
            rows.append([
                str(entry.index),
                str(entry.start_lba),
                str(entry.sector_count),
                _human_size(entry.sector_count * table.sector_size),
                entry.label,
                "yes" if entry.bootable else "",
                "logical" if entry.is_logical else "",
            ])
        buffer = io_table(rows)
        lines.append(buffer)
        chunks.append("\n".join(lines))
        device.close()
    return "\n\n".join(chunks)


def format_scan_result(result, device_path: str) -> str:
    """Render the outcome of a scan as text."""
    lines = [
        f"device : {device_path}",
        f"table  : {result.table_type.upper()}",
        f"mode   : {result.mode}",
        f"time   : {result.elapsed_seconds:.1f}s",
        f"free   : {len(result.regions)} region(s), "
        f"{_human_size(result.bytes_scanned)} examined",
    ]
    if not result.candidates:
        lines.append("")
        lines.append("no lost partition was found")
        return "\n".join(lines)

    rows = []
    for candidate in result.candidates:
        rows.append([
            str(candidate.start_sector),
            str(candidate.sector_count),
            _human_size(candidate.size_bytes),
            candidate.fs_type,
            f"{candidate.confidence * 100:.0f}%",
            candidate.source,
        ])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _print_table(rows, ["start", "sectors", "size", "filesystem", "conf", "evidence"])
    lines.append("")
    lines.append(buffer.getvalue().rstrip())
    lines.append("")
    lines.append("evidence:")
    for candidate in result.candidates:
        lines.append(f"  sector {candidate.start_sector} ({candidate.fs_type}):")
        for item in candidate.evidence:
            lines.append(f"    - {item}")
    return "\n".join(lines)


def scan_device_text(device_spec: str, mode: str = SCAN_MODE_FULL,
                     as_json: bool = False) -> str:
    """Scan a device and return the report."""
    device = open_device(device_spec, read_only=True)
    try:
        table = load_partition_table(device)
        if table is None:
            raise LostPartError("the disk has no partition table to scan around")
        result = scan_disk(device, table, mode=mode)
        if as_json:
            return json.dumps(result.to_dict(), indent=2)
        return format_scan_result(result, str(getattr(device, "path", device_spec)))
    finally:
        device.close()


def browse_partition_text(device_spec: str, start: str, path: str = "") -> str:
    """List the contents of a partition and return the report."""
    device = open_device(device_spec, read_only=True)
    try:
        candidate = LostPartitionCandidate(
            start_sector=int(start),
            sector_count=0,
            fs_type="",
            label="",
            confidence=1.0,
        )
        parts = tuple(part for part in (path or "").split("/") if part)
        result = list_partition(device, candidate, parts)
        rows = []
        for entry in result.entries:
            rows.append([
                "d" if entry.is_dir else "-",
                entry.name,
                "" if entry.is_dir else _human_size(entry.size),
            ])
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _print_table(rows, ["type", "name", "size"])
        return "\n".join([
            f"filesystem : {result.fs_type}",
            f"method     : {result.method}",
            "",
            buffer.getvalue().rstrip(),
        ])
    finally:
        device.close()


def backup_table_text(device_spec: str, output: str) -> str:
    """Back up the partition table of a device and return the report."""
    device = open_device(device_spec, read_only=True)
    try:
        table = load_partition_table(device)
        if table is None:
            raise LostPartError("the disk has no partition table")
        path = Path(output)
        if path.parent and str(path.parent) not in ("", "."):
            path.parent.mkdir(parents=True, exist_ok=True)
        backup = create_backup(device, table, path,
                               device_id=str(getattr(device, "path", device_spec)))
        return (
            f"backup written to {backup.path} "
            f"({len(backup.chunks)} chunk(s), {backup.kind.upper()} table)"
        )
    finally:
        device.close()


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    """List the disks of the machine and their partition tables."""
    print(list_devices_text(args.device))
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan the free space of a disk for lost partitions."""
    device = open_device(args.device, read_only=True)
    try:
        table = load_partition_table(device)
        if table is None:
            print("the disk has no partition table to scan around", file=sys.stderr)
            return 1

        checkpoint = ScanCheckpoint(args.checkpoint) if args.checkpoint else None
        checkpoint_id = None
        if checkpoint is not None:
            checkpoint_id = checkpoint.start(
                device_id=str(getattr(device, "path", args.device)),
                mode=args.mode,
            )

        def progress(fraction: float, message: str) -> None:
            if not args.quiet:
                print(f"\r{progress.last:>6.1f}%  {message[:60]:<60}", end="", file=sys.stderr)
                progress.last = fraction * 100

        progress.last = 0.0

        result = scan_disk(device, table, mode=args.mode, progress=progress)
        if not args.quiet:
            print(file=sys.stderr)

        for candidate in result.candidates:
            if checkpoint is not None and checkpoint_id is not None:
                checkpoint.add_candidate(checkpoint_id, candidate)
        if checkpoint is not None and checkpoint_id is not None:
            checkpoint.set_status(
                checkpoint_id, STATUS_CANCELLED if result.cancelled else STATUS_DONE
            )
        if checkpoint is not None:
            checkpoint.close()

        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(format_scan_result(result, str(getattr(device, "path", args.device))))
        return 0
    finally:
        device.close()


def cmd_recover(args: argparse.Namespace) -> int:
    """Write a partition entry for a recovered candidate."""
    device = open_device(args.device, read_only=False)
    try:
        table = load_partition_table(device)
        if table is None:
            print("the disk has no partition table", file=sys.stderr)
            return 1

        fs_type = args.fs
        if fs_type is None:
            from .fs import registry
            from .fs.base import ProbeContext

            ctx = ProbeContext(
                device=device,
                start_sector=args.start,
                sector_size=device.sector_size,
                total_sectors=device.total_sectors,
            )
            probe = registry.detect_best(ctx)
            if probe is None:
                print("no filesystem recognised at the given sector", file=sys.stderr)
                return 1
            fs_type = probe.fs_type
            print(f"detected filesystem: {fs_type} ({probe.label})")

        candidate = LostPartitionCandidate(
            start_sector=args.start,
            sector_count=args.size,
            fs_type=fs_type,
            label=fs_type,
            confidence=1.0,
        )

        if not args.apply:
            outcome = recover_partition(device, candidate, table, bootable=args.bootable,
                                       dry_run=True)
            print(outcome.message)
            print("\nre-run with --apply to write the change to the disk")
            return 0

        if not args.no_backup:
            backup_dir = Path(args.backup_dir)
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            name = str(getattr(device, "path", "disk")).replace(":", "").replace("\\", "_")
            backup_path = backup_dir / f"{name}-{stamp}.json"
            backup = create_backup(device, table, backup_path,
                                   device_id=str(getattr(device, "path", args.device)))
            print(f"backup written to {backup.path}")

        outcome = recover_partition(device, candidate, table, bootable=args.bootable,
                                   dry_run=False)
        print(outcome.message)
        return 0 if outcome.success else 1
    finally:
        device.close()


def cmd_browse(args: argparse.Namespace) -> int:
    """List the contents of a recovered partition."""
    device = open_device(args.device, read_only=True)
    try:
        candidate = LostPartitionCandidate(
            start_sector=args.start,
            sector_count=args.size,
            fs_type=args.fs or "",
            label="",
            confidence=1.0,
        )
        path = tuple(part for part in args.path.split("/") if part)
        if args.mount:
            result = mount_partition(device, candidate)
        else:
            result = list_partition(device, candidate, path)
        if args.json:
            print(json.dumps({
                "fs_type": result.fs_type,
                "method": result.method,
                "mount_point": result.mount_point,
                "entries": [
                    {
                        "name": entry.name,
                        "is_dir": entry.is_dir,
                        "size": entry.size,
                        "modified": entry.modified,
                    }
                    for entry in result.entries
                ],
            }, indent=2))
            return 0
        rows = []
        for entry in result.entries:
            rows.append([
                "d" if entry.is_dir else "-",
                entry.name,
                "" if entry.is_dir else _human_size(entry.size),
            ])
        _print_table(rows, ["type", "name", "size"])
        return 0
    finally:
        device.close()


def cmd_backup(args: argparse.Namespace) -> int:
    """Save the partition table structures of a disk."""
    print(backup_table_text(args.device, args.output))
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    """Restore a saved partition table onto a disk."""
    backup = load_backup(args.backup)
    device = open_device(args.device, read_only=False)
    try:
        written = restore_backup(device, backup)
        print(f"restored {written} bytes from {backup.path} onto {device.path}")
        return 0
    finally:
        device.close()


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lostpart",
        description="Identify and recover lost disk partitions.",
        epilog="Started without a command, lostpart opens an interactive menu.",
    )
    parser.add_argument("--version", action="version", version=f"lostpart {__version__}")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="increase the log level")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="list disks and partition tables")
    p_list.add_argument("--device", help="device to inspect (default: all)")
    p_list.set_defaults(func=cmd_list)

    p_scan = sub.add_parser("scan", help="scan the free space for lost partitions")
    p_scan.add_argument("--device", required=True, help="device to scan")
    p_scan.add_argument("--mode", choices=[SCAN_MODE_QUICK, SCAN_MODE_FULL],
                        default=SCAN_MODE_FULL)
    p_scan.add_argument("--checkpoint", help="path of the SQLite checkpoint file")
    p_scan.add_argument("--json", action="store_true", help="emit JSON")
    p_scan.add_argument("--quiet", action="store_true", help="do not show the progress")
    p_scan.set_defaults(func=cmd_scan)

    p_recover = sub.add_parser("recover", help="write a partition entry back")
    p_recover.add_argument("--device", required=True)
    p_recover.add_argument("--start", type=int, required=True,
                            help="first sector of the recovered partition")
    p_recover.add_argument("--size", type=int, required=True,
                            help="length of the partition in sectors")
    p_recover.add_argument("--fs", help="filesystem type (detected when omitted)")
    p_recover.add_argument("--bootable", action="store_true")
    p_recover.add_argument("--apply", action="store_true",
                            help="actually write (without it nothing is changed)")
    p_recover.add_argument("--no-backup", action="store_true")
    p_recover.add_argument("--backup-dir", default="lostpart-backups")
    p_recover.set_defaults(func=cmd_recover)

    p_browse = sub.add_parser("browse", help="list the files of a recovered partition")
    p_browse.add_argument("--device", required=True)
    p_browse.add_argument("--start", type=int, required=True)
    p_browse.add_argument("--size", type=int, default=0)
    p_browse.add_argument("--fs", help="filesystem type (detected when omitted)")
    p_browse.add_argument("--path", default="", help="directory inside the partition")
    p_browse.add_argument("--mount", action="store_true",
                          help="mount the partition through the operating system")
    p_browse.add_argument("--json", action="store_true")
    p_browse.set_defaults(func=cmd_browse)

    p_backup = sub.add_parser("backup", help="save the partition table structures")
    p_backup.add_argument("--device", required=True)
    p_backup.add_argument("--output", required=True, help="path of the backup file")
    p_backup.set_defaults(func=cmd_backup)

    p_restore = sub.add_parser("restore", help="restore a saved partition table")
    p_restore.add_argument("--device", required=True)
    p_restore.add_argument("--backup", required=True, help="path of the backup file")
    p_restore.set_defaults(func=cmd_restore)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    from .interactive import console_is_orphaned, pause, run_interactive

    orphaned = console_is_orphaned()
    try:
        if not hasattr(args, "func"):
            # No command: open the interactive menu so a double click on the
            # executable does something visible.
            code = run_interactive()
        else:
            code = int(args.func(args))
    except LostPartError as exc:
        print(f"error: {exc}", file=sys.stderr)
        code = 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        code = 130
    finally:
        if orphaned:
            pause()
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
