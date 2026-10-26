#!/usr/bin/env python3
"""Captura as telas da interface grafica para inspecao visual.

Ferramenta de desenvolvimento: abre a janela do assistente, percorre cada
tela e grava um PNG em ``build/screenshots``.  Nao altera o disco em nenhum
momento -- os dados das telas de resultados e de pre-visualizacao sao
simulados.

Uso::

    python scripts/screenshot_gui.py [--out build/screenshots]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lostpart.scan.model import LostPartitionCandidate  # noqa: E402
from lostpart.ui.app import LostPartApp  # noqa: E402


def _window_handle(root) -> int:
    """Descobre o HWND da janela de alto nivel do Tkinter."""
    import ctypes

    try:
        return int(root.wm_frame(), 16)
    except Exception:
        return int(ctypes.windll.user32.GetAncestor(root.winfo_id(), 2))


def _render_window(hwnd: int, width: int, height: int):
    """Desenha a janela num bitmap usando ``PrintWindow``.

    ``width`` e ``height`` devem ser o tamanho *completo* da janela,
    incluindo a barra de titulo; o DC devolvido por ``GetWindowDC`` cobre
    a janela inteira.

    Funciona mesmo em sessoes sem desktop interativo, ao contrario de uma
    captura de tela da area de trabalho.
    """
    import ctypes
    from ctypes import wintypes

    from PIL import Image

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

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    window_dc = user32.GetWindowDC(hwnd)
    if not window_dc:
        raise RuntimeError("GetWindowDC falhou")
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        # PW_RENDERFULLCONTENT = 2: desenha a janela inteira, inclusive as
        # partesnormally compostas pelo DWM.
        if not user32.PrintWindow(hwnd, memory_dc, 2):
            user32.PrintWindow(hwnd, memory_dc, 0)

        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # de cima para baixo
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB

        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer,
                        ctypes.byref(header), 0)
        return Image.frombuffer("RGB", (width, height), bytes(buffer),
                                "raw", "BGRX", 0, 1)
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def _window_rect(hwnd: int) -> tuple[int, int]:
    """Devolve a largura e a altura totais da janela, com as bordas."""
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    rect = RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def _capture(app: "LostPartApp", output: Path, name: str) -> None:
    """Grava um PNG da janela principal."""
    root = app.root
    root.update_idletasks()
    root.update()
    root.deiconify()
    root.lift()
    root.update()
    time.sleep(0.2)

    hwnd = _window_handle(root)
    width, height = _window_rect(hwnd)
    image = _render_window(hwnd, width, height)
    image.save(output / f"{name}.png")
    root.update()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="build/screenshots")
    args = parser.parse_args()

    output = (ROOT / args.out).resolve()
    output.mkdir(parents=True, exist_ok=True)

    app = LostPartApp()
    app.root.update()

    # 1. Boas-vindas
    _capture(app, output, "01-welcome")

    # 2. Discos (simulado, para nao exigir hardware real)
    app.show("disks")
    app.disk_list.delete(0, "end")
    for label in (
        "\\\\.\\PhysicalDrive0   ·   476,9 GB   ·   GPT   ·   3 partições",
        "\\\\.\\PhysicalDrive1   ·   931,5 GB   ·   MBR   ·   4 partições",
        "\\\\.\\PhysicalDrive2   ·   14,6 GB   ·   GPT   ·   2 partições",
    ):
        app.disk_list.insert("end", label)
    app.disk_entries = ["\\\\.\\PhysicalDrive0", "\\\\.\\PhysicalDrive1",
                        "\\\\.\\PhysicalDrive2"]
    app.disk_list.selection_set(0)
    app._footer("Escolha o disco que deseja analisar.",
                [("Continuar", "Primary.TButton", lambda: None)])
    _capture(app, output, "02-disks")

    # 3. Procurando
    app.show("scan")
    app.scan_bar["value"] = 42
    app.scan_status.configure(text="Procurando sistemas de arquivos… 42%")
    for line in (
        "Procurando sistemas de arquivos no setor 1048576…",
        "Procurando sistemas de arquivos no setor 2097152…",
        "Procurando sistemas de arquivos no setor 3145728…",
        "Espaço livre analisado: 128,4 GB",
    ):
        app._log(line)
    _capture(app, output, "03-scan")

    # 4. Resultados
    app.candidates = [
        LostPartitionCandidate(
            start_sector=1048576, sector_count=262144, fs_type="ntfs",
            label="Windows", confidence=0.97, volume_name="Sistema",
            source="boot sector", evidence=("NTFS DBR válido", "$Bitmap consistente"),
        ),
        LostPartitionCandidate(
            start_sector=2097152, sector_count=524288, fs_type="exfat",
            label="Dados", confidence=0.88, volume_name="MEUS ARQUIVOS",
            source="boot sector", evidence=("assinatura exFAT 0x85",),
        ),
        LostPartitionCandidate(
            start_sector=3145728, sector_count=131072, fs_type="ext4",
            label="Linux", confidence=0.74, volume_name="ubuntu",
            source="superbloco", evidence=("magic 0xEF53",),
        ),
    ]
    app._fill_results()
    app.show("results")
    _capture(app, output, "04-results")

    # 5. Pre-visualizacao
    app.show("preview")
    for item in app.preview_tree.get_children():
        app.preview_tree.delete(item)
    for name, size in (
        ("📁  Documentos", ""),
        ("📁  Fotos", ""),
        ("📄  notas.txt", "2,1 KB"),
        ("📄  orçamento.pdf", "318,4 KB"),
    ):
        app.preview_tree.insert("", "end", values=(name, size))
    app._footer("NTFS — leitura interna (sem montar a partição)",
                [("Voltar", "Secondary.TButton", lambda: None)])
    _capture(app, output, "05-preview")

    # 6. Recuperar
    app.selected = app.candidates[0]
    app.show("recover")
    app.recover_detail.configure(
        text="NTFS  ·  setor 1048576  ·  128,0 MB")
    app._footer("", [("Cancelar", "Secondary.TButton", lambda: None),
                     ("Confirmar recuperação", "Primary.TButton", lambda: None)])
    _capture(app, output, "06-recover")

    # 7. Concluido
    app.show("done")
    app.done_message.configure(
        text="A partição NTFS foi recuperada com sucesso e gravada na tabela "
             "de partições do disco.")
    _capture(app, output, "07-done")

    # Aviso de permissões
    app._show_admin_banner()
    app.root.update()
    _capture(app, output, "08-admin")

    app.destroy()
    print(f"Screenshots gravados em {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
