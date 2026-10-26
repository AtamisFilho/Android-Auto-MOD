"""Menu interativo mostrado quando o lostpart é aberto sem comando.

A interface de linha de comando é a principal, mas um duplo clique no
executável não pode parecer um programa quebrado.  Por isso, sem comando o
programa abre um menu com as mesmas operações -- e, quando a janela do
console foi criada só para ele, assinatura do duplo clique no gerenciador de
arquivos, espera uma tecla antes de fechar.
"""

from __future__ import annotations

import os
import sys

from . import __version__
from .i18n import t
from .scan.scanner import SCAN_MODE_FULL

__all__ = ["run_interactive", "console_is_orphaned", "pause"]


#: Uma marca de ordem de bytes pode chegar à entrada quando as respostas são
#: canalizadas por um shell do Windows.  Dependendo de como o fluxo é
#: decodificado, a marca aparece como U+FEFF ou como os três caracteres em
#: que os bytes UTF-8 se tornam na página de códigos 1252.
_BOM_PREFIXES = ("\ufeff", "\u00ef\u00bb\u00bf")


def _strip_bom(text: str) -> str:
    """Remove uma marca de ordem de bytes do começo de uma resposta."""
    changed = True
    while changed:
        changed = False
        for prefix in _BOM_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):]
                changed = True
                break
    return text


def console_is_orphaned() -> bool:
    """True quando este processo é o único dono do console.

    Um console criado só para o programa é a assinatura de um duplo clique
    no gerenciador de arquivos: ninguém mais tem a janela, então ela
    desaparece no instante em que o programa termina.
    """
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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
    """Espera o usuário antes de a janela do console desaparecer."""
    try:
        if os.name == "nt":
            print()
            input("Pressione Enter para fechar esta janela...")
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


def _prompt(text: str) -> str:
    try:
        answer = input(text)
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(0) from None
    return _strip_bom(answer.strip()).strip()


def run_interactive() -> int:
    """Executa o menu interativo.  Devolve o código de saída."""
    from .cli import (
        backup_table_text,
        browse_partition_text,
        list_devices_text,
        scan_device_text,
    )
    from .ui import console

    console.setup_console()
    console.heading(t("menu.title", version=__version__))
    options = [
        ("1", t("menu.1")),
        ("2", t("menu.2")),
        ("3", t("menu.3")),
        ("4", t("menu.4")),
        ("5", t("menu.5")),
        ("6", t("menu.6")),
        ("0", t("menu.0")),
    ]
    for key, label in options:
        print(f"   {console._paint(key, chr(27) + '[1;36m')}  {label}")
    print()

    while True:
        try:
            choice = _prompt(t("menu.select"))
        except SystemExit:
            return 0

        if choice in ("0", "q", "Q", "sair"):
            console.success(t("menu.bye"))
            return 0

        try:
            if choice == "1":
                device = _prompt(t("menu.device"))
                print()
                print(list_devices_text(device or None))
            elif choice == "2":
                device = _prompt(t("menu.device_scan"))
                mode = _prompt(t("menu.mode")) or SCAN_MODE_FULL
                print()
                print(scan_device_text(device, mode))
            elif choice == "3":
                device = _prompt(t("menu.device_scan"))
                start = _prompt(t("menu.start"))
                path = _prompt(t("menu.path"))
                print()
                print(browse_partition_text(device, start, path))
            elif choice == "4":
                device = _prompt(t("menu.device_scan"))
                output = _prompt(t("menu.output")) or "lostpart-backup.json"
                print()
                print(backup_table_text(device, output))
            elif choice == "5":
                from .ui.app import run_gui

                run_gui()
                return 0
            elif choice == "6":
                from .cli import build_parser

                build_parser().print_help()
            else:
                console.warning(t("menu.unknown"))
        except SystemExit:
            raise
        except Exception as exc:
            console.error(t("menu.error", error=exc))

        print()
        try:
            _prompt(t("menu.back"))
        except SystemExit:
            return 0
        print()
