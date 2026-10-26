"""Paleta, tipografia e estilos compartilhados pela interface.

A interface gráfica e o console usam a mesma paleta, para que o programa
tenha a mesma identidade nos dois lugares.
"""

from __future__ import annotations

__all__ = ["COLORS", "ConsoleColors", "FONT_FAMILY", "apply_theme"]

#: Cores da interface, em hexadecimal.
COLORS: dict[str, str] = {
    # superfícies
    "background": "#f1f5f9",
    "surface": "#ffffff",
    "surface_alt": "#f8fafc",
    "border": "#e2e8f0",
    "border_strong": "#cbd5e1",
    # texto
    "text": "#0f172a",
    "text_muted": "#64748b",
    "text_inverted": "#ffffff",
    # acentos
    "primary": "#2563eb",
    "primary_hover": "#1d4ed8",
    "primary_soft": "#dbeafe",
    "success": "#16a34a",
    "success_soft": "#dcfce7",
    "warning": "#d97706",
    "warning_soft": "#fef3c7",
    "danger": "#dc2626",
    "danger_soft": "#fee2e2",
    "info": "#0891b2",
    "info_soft": "#cffafe",
    "highlight": "#f59e0b",
}

#: Família tipográfica.  Segoe UI acompanha o Windows; DejaVu Sans é o
#: equivalente mais comum no Linux.
FONT_FAMILY = "Segoe UI"

#: Famílias alternativas quando a principal não existe.
FONT_FALLBACKS = ("Segoe UI", "Tahoma", "DejaVu Sans", "Helvetica", "Arial")


class ConsoleColors:
    """Códigos ANSI usados pelo console."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GREY = "\033[90m"
    BG_BLUE = "\033[44m"
    BG_GREEN = "\033[42m"
    BG_GREY = "\033[100m"

    @classmethod
    def all(cls) -> dict[str, str]:
        return {
            name: value
            for name, value in vars(cls).items()
            if name.isupper() and isinstance(value, str)
        }


def apply_theme(root) -> str:
    """Aplica o tema da interface gráfica a uma janela do Tkinter.

    Devolve o nome da fonte efetivamente usada, para que a interface possa
    ajustá-la quando a fonte preferida não existir no sistema.
    """
    import tkinter.font as tkfont

    available = set(tkfont.families(root))
    family = FONT_FAMILY
    for candidate in (FONT_FAMILY, *FONT_FALLBACKS):
        if candidate in available:
            family = candidate
            break

    style = __import__("tkinter.ttk", fromlist=["Style"]).Style(root)
    try:
        style.theme_use("clam")
    except Exception:  # pragma: no cover - depends on the Tk build
        pass

    style.configure(".", font=(family, 10), background=COLORS["background"],
                    foreground=COLORS["text"])
    style.configure("TFrame", background=COLORS["background"])
    style.configure("Surface.TFrame", background=COLORS["surface"])
    style.configure("TLabel", background=COLORS["background"], foreground=COLORS["text"])
    style.configure("Title.TLabel", font=(family, 20, "bold"),
                    background=COLORS["surface"], foreground=COLORS["text"])
    style.configure("Subtitle.TLabel", font=(family, 10),
                    background=COLORS["surface"], foreground=COLORS["text_muted"])
    style.configure("Heading.TLabel", font=(family, 13, "bold"),
                    background=COLORS["background"], foreground=COLORS["text"])
    style.configure("Muted.TLabel", background=COLORS["background"],
                    foreground=COLORS["text_muted"])
    style.configure("CardTitle.TLabel", font=(family, 11, "bold"),
                    background=COLORS["surface"], foreground=COLORS["text"])
    style.configure("CardBody.TLabel", background=COLORS["surface"],
                    foreground=COLORS["text_muted"])

    style.configure("Primary.TButton", font=(family, 10, "bold"),
                    background=COLORS["primary"], foreground=COLORS["text_inverted"],
                    borderwidth=0, focusthickness=0, padding=(18, 10))
    style.map("Primary.TButton",
              background=[("active", COLORS["primary_hover"]),
                          ("disabled", COLORS["border_strong"])])
    style.configure("Secondary.TButton", font=(family, 10),
                    background=COLORS["surface"], foreground=COLORS["text"],
                    borderwidth=1, relief="solid", padding=(14, 8))
    style.map("Secondary.TButton",
              background=[("active", COLORS["primary_soft"])])
    style.configure("Danger.TButton", font=(family, 10, "bold"),
                    background=COLORS["danger"], foreground=COLORS["text_inverted"],
                    borderwidth=0, focusthickness=0, padding=(18, 10))
    style.map("Danger.TButton", background=[("active", "#b91c1c")])
    style.configure("Link.TButton", font=(family, 10),
                    background=COLORS["background"], foreground=COLORS["primary"],
                    borderwidth=0, focusthickness=0, padding=(4, 4))
    style.configure("Link.TButton", foreground=COLORS["primary"])

    style.configure("TEntry", fieldbackground=COLORS["surface"],
                    bordercolor=COLORS["border_strong"], lightcolor=COLORS["surface"],
                    darkcolor=COLORS["surface"], padding=6)
    style.configure("TProgressbar", troughcolor=COLORS["border"],
                    background=COLORS["primary"], borderwidth=0, thickness=8)
    style.configure("Treeview", background=COLORS["surface"],
                    fieldbackground=COLORS["surface"], foreground=COLORS["text"],
                    rowheight=28, borderwidth=0)
    style.configure("Treeview.Heading", font=(family, 10, "bold"),
                    background=COLORS["surface_alt"], foreground=COLORS["text_muted"],
                    relief="flat", borderwidth=0, padding=(6, 8))
    style.map("Treeview", background=[("selected", COLORS["primary_soft"])],
              foreground=[("selected", COLORS["text"])])
    style.configure("TCheckbutton", background=COLORS["surface"],
                    foreground=COLORS["text"])
    style.configure("TRadiobutton", background=COLORS["surface"],
                    foreground=COLORS["text"])
    style.configure("TNotebook", background=COLORS["background"], borderwidth=0)
    style.configure("TNotebook.Tab", padding=(14, 8), font=(family, 10))
    return family
