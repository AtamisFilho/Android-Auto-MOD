"""Interface de linha de comando do lostpart.

Comandos::

    lostpart listar                    lista os discos e suas partições
    lostpart escanear --device N       procura partições perdidas no espaço livre
    lostpart recuperar --device N ...  reescreve a entrada que falta na tabela
    lostpart navegar  --device N ...   mostra o conteúdo de uma partição
    lostpart backup    --device N      salva a tabela de partições
    lostpart restaurar --device N      restaura uma tabela de partições salva
    lostpart grafica                   abre a interface gráfica

Cada comando também aceita o nome em inglês (``list``, ``scan``, ``recover``,
``browse``, ``restore`` e ``gui``), para que scripts antigos continuem
funcionando.

Sem comando, o lostpart abre o menu interativo.
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
from .i18n import format_size, sector_number, t
from .recover.backup import create_backup, load_backup, restore_backup
from .recover.writer import recover_partition
from .scan.checkpoint import STATUS_CANCELLED, STATUS_DONE, ScanCheckpoint
from .scan.model import LostPartitionCandidate
from .scan.scanner import SCAN_MODE_FULL, SCAN_MODE_QUICK, scan_disk
from .tables.table import TABLE_TYPE_GPT, load_partition_table
from .ui import console

__all__ = ["main", "build_parser"]

logger = logging.getLogger("lostpart")


# --------------------------------------------------------------------------
# Operações reutilizadas pela linha de comando e pelo menu
# --------------------------------------------------------------------------


def list_devices_text(device_spec: str | None = None) -> str:
    """Devolve a listagem dos discos e de suas partições."""
    from .device import list_physical_devices

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        if device_spec:
            devices = [open_device(device_spec, read_only=True)]
        else:
            devices = list_physical_devices()

        if not devices:
            console.warning(t("list.none"))
            return buffer.getvalue()

        console.heading(t("list.title"))
        for device in devices:
            try:
                table = load_partition_table(device)
            except LostPartError as exc:
                console.error(str(exc))
                continue
            console.info(str(getattr(device, "path", device)))
            if table is None:
                console.bullet(t("list.no_table"))
                continue
            console.bullet(f"{t('list.table')}: {table.kind.upper()}")
            if table.kind == TABLE_TYPE_GPT and table.gpt_header is not None:
                console.bullet(f"{t('list.disk_guid')}: {table.gpt_header.disk_guid}")
                console.bullet(
                    f"{t('list.crc_header')}: "
                    f"{t('list.crc_ok') if table.header_crc_valid else t('list.crc_bad')}"
                )
                console.bullet(
                    f"{t('list.crc_entries')}: "
                    f"{t('list.crc_ok') if table.entry_array_crc_valid else t('list.crc_bad')}"
                )
            rows = []
            for entry in table.sorted_by_start():
                rows.append([
                    str(entry.index),
                    str(entry.start_lba),
                    str(entry.sector_count),
                    format_size(entry.sector_count * table.sector_size),
                    entry.label,
                    "sim" if entry.bootable else "",
                    "lógica" if entry.is_logical else "",
                ])
            console.table(t("list.columns"), rows,
                          ("right", "right", "right", "right", "left", "center", "center"))
            console.divider()
            device.close()
    return buffer.getvalue()


def format_scan_result(result, device_path: str) -> str:
    """Formata o resultado de uma varredura."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        console.heading(t("scan.found"))
        console.key_values([
            (t("scan.device"), device_path),
            (t("scan.table"), result.table_type.upper()),
            (t("scan.mode"), t("scan.mode_full") if result.mode == SCAN_MODE_FULL
             else t("scan.mode_quick")),
            (t("scan.time"), f"{result.elapsed_seconds:.1f}s"),
            (t("scan.free"), t("scan.regions", count=len(result.regions),
                               size=format_size(result.bytes_scanned))),
        ])
        console.divider()

        if not result.candidates:
            console.warning(t("scan.none"))
            return buffer.getvalue()

        rows = []
        for candidate in result.candidates:
            rows.append([
                str(candidate.start_sector),
                str(candidate.sector_count),
                format_size(candidate.size_bytes),
                candidate.fs_type.upper(),
                f"{candidate.confidence * 100:.0f}%",
                candidate.source,
            ])
        console.table(t("scan.columns"), rows,
                      ("right", "right", "right", "left", "right", "left"))

        console.divider()
        console.heading(t("scan.evidence"))
        for candidate in result.candidates:
            console.info(f"setor {candidate.start_sector}  ({candidate.fs_type})")
            for item in candidate.evidence:
                console.bullet(item)
    return buffer.getvalue()


def scan_device_text(device_spec: str, mode: str = SCAN_MODE_FULL,
                     as_json: bool = False) -> str:
    """Varre um disco e devolve o relatório."""
    device = open_device(device_spec, read_only=True)
    try:
        table = load_partition_table(device)
        if table is None:
            raise LostPartError(t("error.no_table"))
        result = scan_disk(device, table, mode=mode)
        if as_json:
            return json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
        return format_scan_result(result, str(getattr(device, "path", device_spec)))
    finally:
        device.close()


def browse_partition_text(device_spec: str, start: str, path: str = "") -> str:
    """Mostra o conteúdo de uma partição."""
    device = open_device(device_spec, read_only=True)
    try:
        candidate = LostPartitionCandidate(
            start_sector=int(start), sector_count=0, fs_type="", label="", confidence=1.0,
        )
        parts = tuple(part for part in (path or "").split("/") if part)
        result = list_partition(device, candidate, parts)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            console.key_values([
                (t("browse.filesystem"), result.fs_type.upper()),
                (t("browse.method"), t("browse.method_internal")
                 if result.method == "internal" else t("browse.method_native")),
            ])
            console.divider()
            rows = []
            for entry in result.entries:
                rows.append([
                    "📁" if entry.is_dir else "📄",
                    entry.name,
                    "" if entry.is_dir else format_size(entry.size),
                ])
            console.table(t("browse.columns"), rows)
        return buffer.getvalue()
    finally:
        device.close()


def backup_table_text(device_spec: str, output: str) -> str:
    """Salva a tabela de partições de um disco."""
    device = open_device(device_spec, read_only=True)
    try:
        table = load_partition_table(device)
        if table is None:
            raise LostPartError(t("error.no_table"))
        path = Path(output)
        if str(path.parent) not in ("", "."):
            path.parent.mkdir(parents=True, exist_ok=True)
        backup = create_backup(device, table, path,
                               device_id=str(getattr(device, "path", device_spec)))
        return t("backup.done", path=backup.path, chunks=len(backup.chunks),
                 kind=backup.kind.upper())
    finally:
        device.close()


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    print(list_devices_text(args.device))
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    device = open_device(args.device, read_only=True)
    try:
        table = load_partition_table(device)
        if table is None:
            console.error(t("error.no_table"))
            return 1

        checkpoint = ScanCheckpoint(args.checkpoint) if args.checkpoint else None
        checkpoint_id = None
        if checkpoint is not None:
            checkpoint_id = checkpoint.start(
                device_id=str(getattr(device, "path", args.device)), mode=args.mode)

        def progress(fraction: float, message: str) -> None:
            if not args.quiet:
                console.progress(fraction,
                                 t("scan.progress", sector=sector_number(message)))

        result = scan_disk(device, table, mode=args.mode, progress=progress)
        if not args.quiet:
            console.progress_done()

        for candidate in result.candidates:
            if checkpoint is not None and checkpoint_id is not None:
                checkpoint.add_candidate(checkpoint_id, candidate)
        if checkpoint is not None and checkpoint_id is not None:
            checkpoint.set_status(checkpoint_id,
                                  STATUS_CANCELLED if result.cancelled else STATUS_DONE)
        if checkpoint is not None:
            checkpoint.close()

        if args.json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(format_scan_result(result, str(getattr(device, "path", args.device))))
        return 0
    finally:
        device.close()


def cmd_recover(args: argparse.Namespace) -> int:
    device = open_device(args.device, read_only=False)
    try:
        table = load_partition_table(device)
        if table is None:
            console.error(t("error.no_table"))
            return 1

        fs_type = args.fs
        if fs_type is None:
            from .fs import registry
            from .fs.base import ProbeContext

            ctx = ProbeContext(device=device, start_sector=args.start,
                               sector_size=device.sector_size,
                               total_sectors=device.total_sectors)
            probe = registry.detect_best(ctx)
            if probe is None:
                console.error(t("recover.none"))
                return 1
            fs_type = probe.fs_type
            console.info(t("recover.detected", fs=fs_type, label=probe.label))

        candidate = LostPartitionCandidate(
            start_sector=args.start, sector_count=args.size, fs_type=fs_type,
            label=fs_type, confidence=1.0)

        if not args.apply:
            outcome = recover_partition(device, candidate, table,
                                       bootable=args.bootable, dry_run=True)
            console.info(outcome.message)
            console.info(t("recover.dry_run"))
            return 0

        if not args.no_backup:
            folder = Path(args.backup_dir)
            folder.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            name = str(getattr(device, "path", "disco")).replace(":", "").replace("\\", "_")
            path = folder / f"{name}-{stamp}.json"
            create_backup(device, table, path,
                          device_id=str(getattr(device, "path", args.device)))
            console.success(t("recover.backup", path=path))

        console.info(t("recover.write_mbr") if table.kind != TABLE_TYPE_GPT
                     else t("recover.write_gpt"))
        outcome = recover_partition(device, candidate, table,
                                   bootable=args.bootable, dry_run=False)
        console.success(outcome.message)
        return 0 if outcome.success else 1
    finally:
        device.close()


def cmd_browse(args: argparse.Namespace) -> int:
    device = open_device(args.device, read_only=True)
    try:
        candidate = LostPartitionCandidate(
            start_sector=args.start, sector_count=args.size,
            fs_type=args.fs or "", label="", confidence=1.0)
        path = tuple(part for part in args.path.split("/") if part)
        result = mount_partition(device, candidate) if args.mount \
            else list_partition(device, candidate, path)
        if args.json:
            print(json.dumps({
                "fs_type": result.fs_type,
                "method": result.method,
                "mount_point": result.mount_point,
                "entries": [
                    {"name": entry.name, "is_dir": entry.is_dir,
                     "size": entry.size, "modified": entry.modified}
                    for entry in result.entries
                ],
            }, indent=2, ensure_ascii=False))
            return 0
        console.key_values([
            (t("browse.filesystem"), result.fs_type.upper()),
            (t("browse.method"), t("browse.method_internal")
             if result.method == "internal" else t("browse.method_native")),
        ])
        console.divider()
        rows = []
        for entry in result.entries:
            rows.append([
                "📁" if entry.is_dir else "📄",
                entry.name,
                "" if entry.is_dir else format_size(entry.size),
            ])
        console.table(t("browse.columns"), rows)
        return 0
    finally:
        device.close()


def cmd_backup(args: argparse.Namespace) -> int:
    print(backup_table_text(args.device, args.output))
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    backup = load_backup(args.backup)
    device = open_device(args.device, read_only=False)
    try:
        written = restore_backup(device, backup)
        console.success(t("restore.done", bytes=written, source=backup.path,
                          target=device.path))
        return 0
    finally:
        device.close()


def cmd_gui(args: argparse.Namespace) -> int:
    from .ui.app import run_gui

    return run_gui()


# --------------------------------------------------------------------------
# Analisador de argumentos
# --------------------------------------------------------------------------


class _PtBrParser(argparse.ArgumentParser):
    """Analisador de argumentos que escreve a ajuda em português.

    O ``argparse`` fixa os rótulos das seções em inglês; como a interface
    inteira é traduzida, eles são trocados aqui.
    """

    def format_usage(self) -> str:
        return super().format_usage().replace("usage: ", "uso: ", 1)

    def format_help(self) -> str:
        text = super().format_help()
        return (text
                .replace("usage: ", "uso: ", 1)
                .replace("positional arguments:", "argumentos posicionais:")
                .replace("options:", "opções:")
                .replace("optional arguments:", "argumentos opcionais:")
                .replace("show this help message and exit", "mostra esta ajuda e sai"))


def build_parser() -> argparse.ArgumentParser:
    parser = _PtBrParser(
        prog="lostpart",
        description=t("cli.description"),
        epilog=t("cli.usage.tail"),
    )
    parser._positionals.title = "comandos"
    parser._optionals.title = "opções"
    parser.add_argument("--version", action="version", version=f"lostpart {__version__}",
                        help="mostra a versão do programa e sai")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="aumenta o nível de detalhe dos logs")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("listar", aliases=["list"], help=t("cli.command.list"))
    p_list.add_argument("--device", help=t("cli.help.device"))
    p_list.set_defaults(func=cmd_list)

    p_scan = sub.add_parser("escanear", aliases=["scan"], help=t("cli.command.scan"))
    p_scan.add_argument("--device", required=True, help=t("cli.help.device"))
    p_scan.add_argument("--mode", choices=[SCAN_MODE_QUICK, SCAN_MODE_FULL],
                        default=SCAN_MODE_FULL, help=t("cli.help.mode"))
    p_scan.add_argument("--checkpoint", help=t("cli.help.checkpoint"))
    p_scan.add_argument("--json", action="store_true", help=t("cli.help.json"))
    p_scan.add_argument("--quiet", action="store_true", help=t("cli.help.quiet"))
    p_scan.set_defaults(func=cmd_scan)

    p_recover = sub.add_parser("recuperar", aliases=["recover"],
                               help=t("cli.command.recover"))
    p_recover.add_argument("--device", required=True, help=t("cli.help.device"))
    p_recover.add_argument("--start", type=int, required=True, help=t("cli.help.start"))
    p_recover.add_argument("--size", type=int, required=True, help=t("cli.help.size"))
    p_recover.add_argument("--fs", help=t("cli.help.fs"))
    p_recover.add_argument("--bootable", action="store_true", help=t("cli.help.bootable"))
    p_recover.add_argument("--apply", action="store_true", help=t("cli.help.apply"))
    p_recover.add_argument("--no-backup", action="store_true", help=t("cli.help.no_backup"))
    p_recover.add_argument("--backup-dir", default="lostpart-backups",
                           help=t("cli.help.backup_dir"))
    p_recover.set_defaults(func=cmd_recover)

    p_browse = sub.add_parser("navegar", aliases=["browse"], help=t("cli.command.browse"))
    p_browse.add_argument("--device", required=True, help=t("cli.help.device"))
    p_browse.add_argument("--start", type=int, required=True, help=t("cli.help.start"))
    p_browse.add_argument("--size", type=int, default=0, help=t("cli.help.size"))
    p_browse.add_argument("--fs", help=t("cli.help.fs"))
    p_browse.add_argument("--path", default="", help=t("cli.help.path"))
    p_browse.add_argument("--mount", action="store_true", help=t("cli.help.mount"))
    p_browse.add_argument("--json", action="store_true", help=t("cli.help.json"))
    p_browse.set_defaults(func=cmd_browse)

    p_backup = sub.add_parser("backup", help=t("cli.command.backup"))
    p_backup.add_argument("--device", required=True, help=t("cli.help.device"))
    p_backup.add_argument("--output", required=True, help=t("cli.help.output"))
    p_backup.set_defaults(func=cmd_backup)

    p_restore = sub.add_parser("restaurar", aliases=["restore"],
                                help=t("cli.command.restore"))
    p_restore.add_argument("--device", required=True, help=t("cli.help.device"))
    p_restore.add_argument("--backup", required=True, help=t("cli.help.backup"))
    p_restore.set_defaults(func=cmd_restore)

    p_gui = sub.add_parser("grafica", aliases=["gui"], help=t("cli.command.gui"))
    p_gui.set_defaults(func=cmd_gui)

    return parser


def main(argv: list[str] | None = None) -> int:
    console.setup_console()
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
            code = run_interactive()
        else:
            code = int(args.func(args))
    except LostPartError as exc:
        console.error(str(exc))
        code = 2
    except KeyboardInterrupt:
        print("interrompido", file=sys.stderr)
        code = 130
    finally:
        if orphaned:
            pause()
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
