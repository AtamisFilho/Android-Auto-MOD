"""Saída de console redesenhada.

A saída antiga era uma sequência de linhas soltas com nomes de campo em
inglês.  Aqui ela ganha painéis, tabelas alinhadas, cores e rótulos em
português, sem perder a utilidade de copiar e colar o resultado.

As cores são ativadas quando o terminal suporta sequências ANSI.  No
Windows isso exige habilitar o modo de processamento virtual do console, o
que é feito automaticamente e sem efeito colateral quando não é possível.
"""

from __future__ import annotations

import os
import shutil
import sys

from ..i18n import format_size

__all__ = [
    "enable_ansi",
    "supports_color",
    "setup_console",
    "panel",
    "table",
    "key_values",
    "progress",
    "progress_done",
    "paint",
    "success",
    "warning",
    "error",
    "info",
    "bullet",
    "heading",
    "divider",
    "human_size",
]

_ansi_enabled: bool | None = None


def setup_console() -> None:
    """Prepara a saida padrao para textos com acentos e simbolos.

    Num console do Windows o Python escreve em UTF-16 e nao ha problema.  Mas
    quando a saida e redirecionada para um arquivo ou um pipe, o console usa
    a codificacao local (cp1252 no Brasil), que nao conhece os caracteres de
    moldura usados nos paineis.  Nesse caso a saida passa a UTF-8, que e o
    que os programas modernos esperam.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if not stream.isatty():
                reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover - depende do ambiente
            pass


def enable_ansi() -> bool:
    """Habilita o processamento de sequências ANSI.  Devolve se deu certo."""
    global _ansi_enabled
    if _ansi_enabled is not None:
        return _ansi_enabled

    if os.environ.get("NO_COLOR"):
        _ansi_enabled = False
        return False

    if os.name != "nt":
        _ansi_enabled = sys.stdout.isatty()
        return _ansi_enabled

    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32(0)
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            _ansi_enabled = False
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if not kernel32.SetConsoleMode(handle, mode.value | 0x0004):
            _ansi_enabled = False
            return False
        _ansi_enabled = True
    except Exception:
        _ansi_enabled = False
    return _ansi_enabled


def supports_color() -> bool:
    """True quando o terminal aceita cores."""
    return enable_ansi()


def _paint(text: str, code: str) -> str:
    if not enable_ansi():
        return text
    return f"{code}{text}\033[0m"


def paint(text: str, code: str) -> str:
    """Colour a piece of text, when the terminal supports it.

    This is the public name; :func:`_paint` is kept as an alias.
    """
    return _paint(text, code)


def _width(text: str) -> int:
    """Largura visível de uma string, ignorando os códigos de cor."""
    length = 0
    index = 0
    while index < len(text):
        if text[index] == "\033":
            end = text.find("m", index)
            if end == -1:
                break
            index = end + 1
            continue
        length += 1
        index += 1
    return length


def _pad(text: str, width: int, align: str = "left") -> str:
    filler = max(0, width - _width(text))
    if align == "right":
        return " " * filler + text
    if align == "center":
        left = filler // 2
        return " " * left + text + " " * (filler - left)
    return text + " " * filler


def human_size(size: int | float) -> str:
    """Formato de tamanho legível."""
    return format_size(size)


def heading(title: str, subtitle: str = "") -> None:
    """Cabeçalho principal do programa."""
    print()
    print(_paint(title, "\033[1;36m"))
    if subtitle:
        print(_paint(subtitle, "\033[90m"))
    print()


def divider(char: str = "─", width: int = 64) -> None:
    """Linha divisória."""
    print(_paint(char * width, "\033[90m"))


def panel(title: str, lines: list[str], color: str = "\033[36m") -> None:
    """Um painel com bordas, usado para os blocos de destaque."""
    width = 64
    inner = width - 2
    print(_paint("╭" + "─" * inner + "╮", color))
    print(_paint("│", color) + _paint(f" {title}".ljust(inner), "\033[1m")
          + _paint("│", color))
    for line in lines:
        for piece in (line or " ").split("\n"):
            print(_paint("│", color) + _paint(f" {piece}".ljust(inner), "")
                  + _paint("│", color))
    print(_paint("╰" + "─" * inner + "╯", color))


def key_values(pairs: list[tuple[str, str]], indent: str = "  ") -> None:
    """Lista de rótulos e valores alinhados."""
    if not pairs:
        return
    width = max(len(str(key)) for key, _ in pairs)
    for key, value in pairs:
        label = _paint(f"{str(key):<{width}}", "\033[90m")
        print(f"{indent}{label}  {value}")


def table(headers: tuple[str, ...], rows: list[list[str]],
          aligns: tuple[str, ...] | None = None, indent: str = "  ") -> None:
    """Tabela com colunas alinhadas."""
    if not rows:
        print(f"{indent}(nenhum resultado)")
        return
    if aligns is None:
        aligns = tuple("left" for _ in headers)
    if len(aligns) < len(headers):
        aligns = tuple(aligns) + ("left",) * (len(headers) - len(aligns))

    # A row with a different number of cells than the header must not break
    # the layout.  Extra cells get a column of their own instead of being
    # dropped, and missing ones are left empty.
    columns = max([len(headers)] + [len(row) for row in rows])
    if len(aligns) < columns:
        aligns = tuple(aligns) + ("left",) * (columns - len(aligns))
    headers = list(headers) + [""] * (columns - len(headers))

    widths = [len(str(header)) for header in headers]
    for row in rows:
        for index, cell in enumerate(row[:columns]):
            widths[index] = max(widths[index], _width(str(cell)))

    def render(cells: list[str], bold: bool = False) -> str:
        parts = []
        for index in range(columns):
            cell = cells[index] if index < len(cells) else ""
            text = _pad(str(cell), widths[index], aligns[index])
            parts.append(_paint(text, "\033[1m") if bold else text)
        return indent + "  ".join(parts)

    print(render(list(headers), bold=True))
    print(indent + "  ".join("─" * width for width in widths))
    for row in rows:
        print(render([str(cell) for cell in row]))


def progress(fraction: float, message: str = "", width: int = 28) -> None:
    """Barra de progresso de uma linha."""
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    bar = "█" * filled + "░" * (width - filled)
    line = f"  {bar} {fraction * 100:5.1f}%"
    if message:
        line += f"  {message}"
    sys.stdout.write("\r" + line.ljust(100))
    sys.stdout.flush()


def progress_done() -> None:
    """Encerra a linha da barra de progresso."""
    sys.stdout.write("\r" + " " * 100 + "\r")
    sys.stdout.flush()


def success(text: str) -> None:
    print(f"  {_paint('✓', '\033[32m')} {text}")


def warning(text: str) -> None:
    print(f"  {_paint('!', '\033[33m')} {text}")


def error(text: str) -> None:
    print(f"  {_paint('✗', '\033[31m')} {text}")


def info(text: str) -> None:
    print(f"  {_paint('i', '\033[36m')} {text}")


def bullet(text: str, indent: str = "    ") -> None:
    """Um item de lista com marcador."""
    print(f"{indent}{_paint('•', '\033[90m')} {text}")
