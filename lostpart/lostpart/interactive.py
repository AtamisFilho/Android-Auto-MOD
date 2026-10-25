"""Interactive menu shown when :mod:`lostpart` is started without a command.

The command line interface is the primary interface of the tool, but a
double click on the executable must not look like a broken program.  When
``lostpart`` is started with no arguments it therefore opens a small menu
that drives the same operations, and -- when the console window was created
for the process alone, which is what happens on a double click from the
file manager -- it waits for a key press before closing.
"""

from __future__ import annotations

import os
import sys

from . import __version__

__all__ = ["run_interactive", "console_is_orphaned", "pause"]


def console_is_orphaned() -> bool:
    """True when this process is the only one attached to the console.

    A console that was created for the program alone is the signature of a
    double click in the file manager: nobody else owns the window, so it
    disappears the moment the program exits.
    """
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            count = ctypes.c_ulong(0)
            kernel32.GetConsoleProcessList(
                ctypes.byref(ctypes.c_ulong(0)), 0
            )
            # Ask for the size first, then for the list.
            kernel32.GetConsoleProcessList(None, 0)
            needed = ctypes.c_ulong(0)
            if kernel32.GetConsoleProcessList(None, ctypes.byref(needed)) == 0:
                return False
            buffer = (ctypes.c_ulong * max(1, needed.value))()
            written = ctypes.c_ulong(0)
            if kernel32.GetConsoleProcessList(buffer, ctypes.byref(written)) == 0:
                return False
            return written.value <= 1
        except Exception:
            return False
    if os.name == "posix":
        try:
            if sys.stdin is not None and sys.stdin.isatty():
                return False
        except Exception:
            return False
        try:
            return os.open("/dev/tty", os.O_RDONLY) >= 0
        except OSError:
            return False
    return False


def pause() -> None:
    """Wait for the user before the console window disappears."""
    try:
        if os.name == "nt":
            print()
            input("Press Enter to close this window...")
        else:
            try:
                with open("/dev/tty", "r") as tty:
                    print()
                    tty.readline()
            except OSError:
                input()
    except (EOFError, KeyboardInterrupt):
        pass
    except Exception:  # pragma: no cover - defensive
        pass


#: A byte order mark can reach the input when the answers are piped in from
#: a Windows shell.  Depending on how the stream is decoded the mark appears
#: either as U+FEFF or as the three characters the UTF-8 bytes turn into
#: under code page 1252.
_BOM_PREFIXES = ("\ufeff", "\u00ef\u00bb\u00bf")


def _strip_bom(text: str) -> str:
    """Remove a leading byte order mark from an answer."""
    changed = True
    while changed:
        changed = False
        for prefix in _BOM_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):]
                changed = True
                break
    return text


def _prompt(text: str) -> str:
    try:
        answer = input(text)
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(0) from None
    return _strip_bom(answer.strip()).strip()


def run_interactive() -> int:
    """Run the interactive menu.  Returns the process exit code."""
    from .cli import (
        browse_partition_text,
        list_devices_text,
        scan_device_text,
        backup_table_text,
    )

    print(f"lostpart {__version__} - identify and recover lost disk partitions")
    print()
    print("  1) List the disks and their partition tables")
    print("  2) Scan a disk for lost partitions")
    print("  3) Preview the contents of a partition")
    print("  4) Back up the partition table of a disk")
    print("  5) Show the command line options")
    print("  0) Exit")
    print()

    while True:
        try:
            choice = _prompt("Select an option: ")
        except SystemExit:
            return 0

        if choice in ("0", "q", "Q", "exit"):
            print("Bye.")
            return 0

        try:
            if choice == "1":
                device = _prompt("Device (number, path or image file): ")
                print()
                print(list_devices_text(device or None))
            elif choice == "2":
                device = _prompt("Device to scan: ")
                mode = _prompt("Mode (full/quick) [full]: ") or "full"
                print()
                print(scan_device_text(device, mode))
            elif choice == "3":
                device = _prompt("Device: ")
                start = _prompt("First sector of the partition: ")
                path = _prompt("Directory inside the partition (blank for the root): ")
                print()
                print(browse_partition_text(device, start, path))
            elif choice == "4":
                device = _prompt("Device: ")
                output = _prompt("Backup file [lostpart-backup.json]: ") or "lostpart-backup.json"
                print()
                print(backup_table_text(device, output))
            elif choice == "5":
                from .cli import build_parser

                build_parser().print_help()
            else:
                print("Unknown option. Choose a number between 0 and 5.")
        except SystemExit:
            raise
        except Exception as exc:
            print(f"\nerror: {exc}")

        print()
        try:
            _prompt("Press Enter to return to the menu...")
        except SystemExit:
            return 0
        print()
