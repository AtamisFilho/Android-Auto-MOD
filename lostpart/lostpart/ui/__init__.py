"""Interface do lostpart: a janela do assistente e a saída de console."""

from __future__ import annotations

__all__ = ["console", "theme"]


def __getattr__(name: str):
    """Importa os submodules sob demanda."""
    if name in ("console", "theme", "app"):
        import importlib

        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(name)
