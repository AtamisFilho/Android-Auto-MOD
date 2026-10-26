"""Captura a janela de um executavel ja empacotado.

Serve para conferir que a interface grafica funciona dentro do binario
publicado, e nao apenas quando roda a partir do codigo.

Uso::

    python scripts/capture_exe.py <executavel> <saida.png> [segundos]
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def find_window(title_part: str) -> int:
    """Procura a janela cujo titulo contem ``title_part``."""
    user32 = ctypes.windll.user32
    found: list[int] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    def callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if title_part.lower() in buffer.value.lower():
                found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found[0] if found else 0


def capture(hwnd: int, output: str) -> None:
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top

    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        user32.PrintWindow(hwnd, memory_dc, 2)
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer,
                        ctypes.byref(header), 0)
        Image.frombuffer("RGB", (width, height), bytes(buffer),
                         "raw", "BGRX", 0, 1).save(output)
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def main() -> int:
    executable = sys.argv[1]
    output = sys.argv[2]
    wait = float(sys.argv[3]) if len(sys.argv) > 3 else 8.0

    process = subprocess.Popen([executable, "grafica"])
    try:
        deadline = time.time() + wait
        hwnd = 0
        while time.time() < deadline:
            hwnd = find_window("lostpart")
            if hwnd:
                break
            time.sleep(0.4)
        if not hwnd:
            print("a janela do programa nao apareceu")
            return 1
        time.sleep(1.5)
        capture(hwnd, output)
        print(f"capturado em {output}")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except Exception:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
