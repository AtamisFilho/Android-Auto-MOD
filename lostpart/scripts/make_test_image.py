"""Gera uma imagem de disco de teste para exercitar o console."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import make_disk_with_ntfs  # noqa: E402

target = Path(sys.argv[1])
data = make_disk_with_ntfs()
target.write_bytes(data)
print(f"imagem criada: {target} ({len(data)} bytes)")
