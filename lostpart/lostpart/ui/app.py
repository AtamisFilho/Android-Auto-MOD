"""Interface gráfica do lostpart.

A interface é um assistente em cinco passos, pensado para quem não usa
ferramentas de disco no dia a dia:

1. **Boas-vindas** -- o que o programa faz e o botão para começar.
2. **Escolher o disco** -- a lista dos discos com tamanho e partições.
3. **Procurando** -- o progresso e o que está acontecendo, em português.
4. **Resultados** -- o que foi encontrado, com a confiança de cada achado.
5. **Recuperar** -- a explicação do que vai acontecer, o backup e a
   confirmação.

A varredura roda em uma thread separada para que a janela nunca congele.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk

from .. import __version__
from ..device import DeviceError, PermissionError_, open_device
from ..errors import LostPartError
from ..i18n import format_size, sector_number, t
from ..recover.backup import create_backup
from ..recover.writer import recover_partition
from ..scan.model import LostPartitionCandidate
from ..scan.scanner import scan_disk
from ..tables.table import TABLE_TYPE_GPT, load_partition_table
from .theme import COLORS, apply_theme

__all__ = ["LostPartApp", "run_gui"]


class Screen(tk.Frame):
    """Uma tela do assistente."""

    def __init__(self, master: "LostPartApp"):
        # As telas vivem no corpo da janela; o mestre do Tkinter e o
        # aplicativo, que nao e um widget.
        super().__init__(master.body, bg=COLORS["background"])
        self.app = master


class LostPartApp:
    """A janela principal."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"{t('app.name')} {__version__} - {t('app.tagline')}")
        self.root.geometry("880x620")
        self.root.minsize(760, 520)
        self.family = apply_theme(self.root)

        self.screens: dict[str, Screen] = {}
        self.current: Screen | None = None
        self.device_spec: str | None = None
        self.device_path: str = ""
        self.table = None
        self.candidates: list[LostPartitionCandidate] = []
        self.selected: LostPartitionCandidate | None = None
        self.messages: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._closing = False

        self._build()
        self.show("welcome")

    # ------------------------------------------------------------------
    # Estrutura da janela
    # ------------------------------------------------------------------
    def _build(self) -> None:
        self.root.configure(bg=COLORS["background"])

        header = tk.Frame(self.root, bg=COLORS["surface"], height=74)
        header.grid(row=0, column=0, sticky="ew")
        header.pack_propagate(False)
        tk.Label(
            header, text=f"  {t('app.name')}", font=(self.family, 15, "bold"),
            bg=COLORS["surface"], fg=COLORS["text"], anchor="w",
        ).pack(side="left", pady=(14, 0))
        tk.Label(
            header, text=t("app.tagline"), font=(self.family, 10),
            bg=COLORS["surface"], fg=COLORS["text_muted"], anchor="w",
        ).pack(side="left", pady=(20, 0), padx=(2, 0))
        tk.Label(
            header, text=f"v{__version__}", font=(self.family, 9),
            bg=COLORS["surface"], fg=COLORS["text_muted"], anchor="e",
        ).pack(side="right", padx=16)

        self.body = tk.Frame(self.root, bg=COLORS["background"])
        self.body.grid(row=1, column=0, sticky="nsew")

        self.admin_bar = self._build_admin_banner()
        self.admin_bar.grid(row=2, column=0, sticky="ew")
        self.admin_bar.grid_remove()

        self.footer = tk.Frame(self.root, bg=COLORS["background"], height=64)
        self.footer.grid(row=3, column=0, sticky="ew")
        self.footer.pack_propagate(False)
        self.hint = tk.Label(
            self.footer, text="", font=(self.family, 9),
            bg=COLORS["background"], fg=COLORS["text_muted"], anchor="w",
        )
        self.hint.pack(side="left", padx=20, pady=18)

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=0)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_rowconfigure(2, weight=0)
        self.root.grid_rowconfigure(3, weight=0)

        self._build_welcome()
        self._build_disks()
        self._build_scan()
        self._build_results()
        self._build_preview()
        self._build_recover()
        self._build_done()

    def show(self, name: str) -> None:
        """Troca para uma das telas."""
        screen = self.screens.get(name)
        if screen is None:
            return
        if self.current is not None:
            self.current.pack_forget()
        screen.pack(fill="both", expand=True)
        self.current = screen

    def _footer(self, left: str = "", buttons: list[tuple[str, str, str]] | None = None) -> None:
        """Redesenha a barra de botões."""
        for child in self.footer.winfo_children():
            child.destroy()
        self.hint = tk.Label(
            self.footer, text=left, font=(self.family, 9),
            bg=COLORS["background"], fg=COLORS["text_muted"], anchor="w",
        )
        self.hint.pack(side="left", padx=20, pady=18)
        for label, style, action in (buttons or []):
            ttk.Button(self.footer, text=label, style=style, command=action).pack(
                side="right", padx=(8, 20), pady=14)

    # ------------------------------------------------------------------
    # 1. Boas-vindas
    # ------------------------------------------------------------------
    def _build_welcome(self) -> None:
        screen = Screen(self)
        self.screens["welcome"] = screen

        card = tk.Frame(screen, bg=COLORS["surface"])
        card.place(relx=0.5, rely=0.5, anchor="center", width=640, height=430)
        tk.Frame(card, bg=COLORS["primary"], height=4).pack(fill="x", side="top")

        inner = tk.Frame(card, bg=COLORS["surface"])
        inner.pack(fill="both", expand=True, padx=40, pady=26)

        tk.Label(inner, text=t("gui.welcome.title"), font=(self.family, 20, "bold"),
                 bg=COLORS["surface"], fg=COLORS["text"], anchor="w",
                 justify="left").pack(fill="x")
        tk.Label(inner, text=t("gui.welcome.subtitle"), font=(self.family, 11),
                 bg=COLORS["surface"], fg=COLORS["text_muted"], anchor="w",
                 justify="left", wraplength=540).pack(fill="x", pady=(6, 16))

        tk.Label(inner, text=t("gui.welcome.how"), font=(self.family, 11, "bold"),
                 bg=COLORS["surface"], fg=COLORS["text"], anchor="w").pack(fill="x")
        steps = tk.Frame(inner, bg=COLORS["surface"])
        steps.pack(fill="x", pady=(8, 0))
        for step in ("gui.welcome.step1", "gui.welcome.step2", "gui.welcome.step3"):
            tk.Label(steps, text=t(step), font=(self.family, 10),
                     bg=COLORS["surface"], fg=COLORS["text"], anchor="w",
                     justify="left").pack(fill="x", pady=2)

        safety = tk.Frame(inner, bg=COLORS["success_soft"])
        safety.pack(fill="x", pady=(16, 0))
        tk.Label(safety, text=t("gui.welcome.safety"), font=(self.family, 9),
                 bg=COLORS["success_soft"], fg=COLORS["success"], justify="left",
                 anchor="w", wraplength=520).pack(fill="x", padx=14, pady=12)

        ttk.Button(inner, text=t("gui.welcome.start"), style="Primary.TButton",
                   command=self._on_start).pack(anchor="w", pady=(18, 0))

    def _on_start(self) -> None:
        self._load_disks()
        self.show("disks")

    # ------------------------------------------------------------------
    # 2. Escolher o disco
    # ------------------------------------------------------------------
    def _build_disks(self) -> None:
        screen = Screen(self)
        self.screens["disks"] = screen
        tk.Label(screen, text=t("gui.disk.title"), font=(self.family, 18, "bold"),
                 bg=COLORS["background"], fg=COLORS["text"]).pack(anchor="w", padx=28, pady=(24, 2))
        tk.Label(screen, text=t("gui.disk.subtitle"), font=(self.family, 10),
                 bg=COLORS["background"], fg=COLORS["text_muted"]).pack(anchor="w", padx=28)

        self.disk_list = tk.Listbox(
            screen, font=(self.family, 10), activestyle="dotbox",
            bg=COLORS["surface"], fg=COLORS["text"], selectmode="browse",
            highlightthickness=1, highlightbackground=COLORS["border_strong"],
            borderwidth=0,
        )
        self.disk_list.pack(fill="both", expand=True, padx=28, pady=16)
        self.disk_entries: list[str] = []
        self.disk_index = tk.IntVar(value=-1)
        self.disk_list.bind("<<ListboxSelect>>", self._on_disk_selected)
        self.disk_list.bind("<Double-Button-1>", lambda _e: self._on_scan_clicked())

    def _load_disks(self) -> None:
        from ..device import list_physical_device_specs

        self.disk_list.delete(0, "end")
        self.disk_entries = []
        specs = list_physical_device_specs()
        if not specs:
            self.disk_list.insert("end", t("gui.disk.empty"))
            self.disk_entries = []
            return
        for spec in specs:
            label = spec
            try:
                device = open_device(spec, read_only=True)
            except (DeviceError, PermissionError_) as exc:
                self.disk_list.insert("end", f"{spec}  —  {exc}")
                self.disk_entries.append(spec)
                continue
            try:
                table = load_partition_table(device)
                size = format_size(device.size)
                if table is None:
                    label = f"{spec}   ·   {size}   ·   {t('list.no_table')}"
                else:
                    count = len(table.occupied)
                    plural = "partição" if count == 1 else "partições"
                    label = (f"{spec}   ·   {size}   ·   {table.kind.upper()}   ·   "
                             f"{count} {plural}")
                self.device_path = str(getattr(device, "path", spec))
            except Exception as exc:  # pragma: no cover - defensive
                label = f"{spec}  —  {exc}"
            finally:
                device.close()
            self.disk_list.insert("end", label)
            self.disk_entries.append(spec)

    def _on_disk_selected(self, _event: object) -> None:
        selection = self.disk_list.curselection()
        if selection:
            self.disk_index = tk.IntVar(value=selection[0])

    def _on_scan_clicked(self) -> None:
        selection = self.disk_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self.disk_entries):
            return
        self.device_spec = self.disk_entries[index]
        self.show("scan")
        self._start_scan()

    # ------------------------------------------------------------------
    # 3. Procurando
    # ------------------------------------------------------------------
    def _build_scan(self) -> None:
        screen = Screen(self)
        self.screens["scan"] = screen
        tk.Label(screen, text=t("gui.scan.title"), font=(self.family, 18, "bold"),
                 bg=COLORS["background"], fg=COLORS["text"]).pack(anchor="w", padx=28, pady=(24, 2))
        tk.Label(screen, text=t("gui.scan.subtitle"), font=(self.family, 10),
                 bg=COLORS["background"], fg=COLORS["text_muted"]).pack(anchor="w", padx=28)

        self.scan_status = tk.Label(screen, text=t("gui.scan.working"),
                                    font=(self.family, 12, "bold"),
                                    bg=COLORS["background"], fg=COLORS["text"])
        self.scan_status.pack(anchor="w", padx=28, pady=(28, 10))

        self.scan_bar = ttk.Progressbar(screen, mode="determinate", maximum=100.0,
                                        length=780)
        self.scan_bar.pack(anchor="w", padx=28)

        self.scan_log = tk.Text(screen, font=("Consolas", 9), height=14,
                                bg=COLORS["surface"], fg=COLORS["text"],
                                relief="flat", highlightthickness=1,
                                highlightbackground=COLORS["border"])
        self.scan_log.pack(fill="both", expand=True, padx=28, pady=16)
        self.scan_log.configure(state="disabled")

    def _log(self, text: str) -> None:
        self.scan_log.configure(state="normal")
        self.scan_log.insert("end", text + "\n")
        self.scan_log.see("end")
        self.scan_log.configure(state="disabled")

    def _start_scan(self) -> None:
        self.candidates = []
        self.scan_log.configure(state="normal")
        self.scan_log.delete("1.0", "end")
        self.scan_log.configure(state="disabled")
        self.scan_bar["value"] = 0
        self.scan_status.configure(text=t("gui.scan.working"))
        self._thread = threading.Thread(target=self._scan_worker, daemon=True)
        self._thread.start()
        self.root.after(120, self._poll_scan)

    def _scan_worker(self) -> None:
        try:
            device = open_device(self.device_spec or "", read_only=True)
        except Exception as exc:
            self.messages.put(("error", str(exc)))
            return
        try:
            table = load_partition_table(device)
            if table is None:
                self.messages.put(("error", t("error.no_table")))
                return

            def progress(fraction: float, message: str) -> None:
                self.messages.put(("progress", (fraction, message)))

            result = scan_disk(device, table, progress=progress)
            self.messages.put(("done", result))
        except Exception as exc:  # pragma: no cover - defensive
            self.messages.put(("error", str(exc)))
        finally:
            device.close()

    def _poll_scan(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "progress":
                    fraction, message = payload
                    self.scan_bar["value"] = fraction * 100
                    self.scan_status.configure(
                        text=f"{t('gui.scan.working')} {fraction * 100:.0f}%")
                    self._log(self._friendly_progress(message))
                elif kind == "done":
                    self.candidates = payload.candidates
                    self.scan_status.configure(text=t("gui.scan.done"))
                    self.scan_bar["value"] = 100
                    self._fill_results()
                    self.show("results")
                    return
                elif kind == "error":
                    self.scan_status.configure(text=payload)
                    self._log(payload)
                    self._footer(t("menu.back"), [("Voltar", "Secondary.TButton",
                                                   lambda: self.show("disks"))])
                    return
        except queue.Empty:
            pass
        if not self._closing:
            self.root.after(120, self._poll_scan)

    def _friendly_progress(self, message: str) -> str:
        """Traduz a mensagem interna da varredura para algo compreensível."""
        return f"Procurando sistemas de arquivos no setor {sector_number(message)}…"

    # ------------------------------------------------------------------
    # 4. Resultados
    # ------------------------------------------------------------------
    def _build_results(self) -> None:
        screen = Screen(self)
        self.screens["results"] = screen
        tk.Label(screen, text=t("gui.results.title"), font=(self.family, 18, "bold"),
                 bg=COLORS["background"], fg=COLORS["text"]).pack(anchor="w", padx=28, pady=(24, 2))
        tk.Label(screen, text=t("gui.results.subtitle"), font=(self.family, 10),
                 bg=COLORS["background"], fg=COLORS["text_muted"]).pack(anchor="w", padx=28)

        self.result_frame = tk.Frame(screen, bg=COLORS["surface"])
        self.result_frame.pack(fill="both", expand=True, padx=28, pady=16)

        # A barra de acoes fica no rodape do quadro, para que os botoes
        # nunca sejam cortados pela arvore de resultados.
        self.result_actions = tk.Frame(self.result_frame, bg=COLORS["surface"])
        self.result_actions.pack(side="bottom", fill="x")

        self.result_tree = ttk.Treeview(
            self.result_frame,
            columns=("start", "size", "fs", "confidence"),
            show="headings", selectmode="browse",
        )
        self.result_tree.heading("start", text=t("gui.results.column"))
        self.result_tree.heading("size", text=t("gui.results.size"))
        self.result_tree.heading("fs", text=t("gui.results.filesystem"))
        self.result_tree.heading("confidence", text=t("gui.results.confidence"))
        self.result_tree.column("start", width=130, anchor="w")
        self.result_tree.column("size", width=120, anchor="w")
        self.result_tree.column("fs", width=130, anchor="w")
        self.result_tree.column("confidence", width=110, anchor="w")
        self.result_tree.pack(fill="both", expand=True, padx=1, pady=1)
        self.result_tree.bind("<Double-Button-1>", lambda _e: self._on_preview())

        self.result_empty = tk.Label(self.result_frame, text=t("gui.results.none"),
                                     font=(self.family, 11),
                                     bg=COLORS["surface"], fg=COLORS["text_muted"],
                                     wraplength=600, justify="center")

        self.preview_button = ttk.Button(self.result_actions,
                                          text=t("gui.results.preview"),
                                          style="Secondary.TButton",
                                          command=self._on_preview)
        self.recover_button = ttk.Button(self.result_actions,
                                         text=t("gui.results.recover"),
                                         style="Primary.TButton",
                                         command=self._on_recover)

    def _fill_results(self) -> None:
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        if not self.candidates:
            self.result_tree.pack_forget()
            if not self.result_empty.winfo_ismapped():
                self.result_empty.pack(expand=True)
            self.preview_button.pack_forget()
            self.recover_button.pack_forget()
            self._footer("", [("Voltar", "Secondary.TButton",
                               lambda: self.show("disks"))])
            return
        if self.result_empty.winfo_ismapped():
            self.result_empty.pack_forget()
        self.result_tree.pack(fill="both", expand=True, padx=1, pady=1)
        for index, candidate in enumerate(self.candidates):
            confidence = f"{candidate.confidence * 100:.0f}%"
            self.result_tree.insert(
                "", "end", iid=str(index),
                values=(f"setor {candidate.start_sector}",
                        format_size(candidate.size_bytes),
                        candidate.fs_type.upper(),
                        confidence),
            )
        self.result_tree.selection_set("0")
        self._on_result_selected()
        self.preview_button.pack(side="left", padx=(12, 0), pady=(0, 12))
        self.recover_button.pack(side="left", padx=(8, 0), pady=(0, 12))
        self._footer("", [("Voltar", "Secondary.TButton",
                           lambda: self.show("disks"))])

    def _on_result_selected(self, _event: object = None) -> None:
        selection = self.result_tree.selection()
        if not selection:
            return
        self.selected = self.candidates[int(selection[0])]

    # ------------------------------------------------------------------
    # 5. Pré-visualização
    # ------------------------------------------------------------------
    def _build_preview(self) -> None:
        screen = Screen(self)
        self.screens["preview"] = screen
        tk.Label(screen, text=t("gui.preview.title"), font=(self.family, 18, "bold"),
                 bg=COLORS["background"], fg=COLORS["text"]).pack(anchor="w", padx=28, pady=(24, 2))
        tk.Label(screen, text=t("gui.preview.subtitle"), font=(self.family, 10),
                 bg=COLORS["background"], fg=COLORS["text_muted"]).pack(anchor="w", padx=28)

        self.preview_tree = ttk.Treeview(screen, columns=("name", "size"),
                                         show="headings", selectmode="browse")
        self.preview_tree.heading("name", text=t("browse.columns")[1])
        self.preview_tree.heading("size", text=t("browse.columns")[2])
        self.preview_tree.column("name", width=460, anchor="w")
        self.preview_tree.column("size", width=160, anchor="w")
        self.preview_tree.pack(fill="both", expand=True, padx=28, pady=16)

    def _on_preview(self) -> None:
        if self.selected is None:
            return
        from ..browse.lister import list_partition

        try:
            device = open_device(self.device_spec or "", read_only=True)
        except Exception as exc:
            self._show_error(str(exc))
            return
        try:
            result = list_partition(device, self.selected)
        except Exception as exc:
            self._show_error(str(exc))
            return
        finally:
            device.close()

        for item in self.preview_tree.get_children():
            self.preview_tree.delete(item)
        for entry in result.entries:
            marker = "📁" if entry.is_dir else "📄"
            self.preview_tree.insert(
                "", "end",
                values=(f"{marker}  {entry.name}",
                        "" if entry.is_dir else format_size(entry.size)),
            )
        self.show("preview")
        self._footer(f"{result.fs_type} — {t('browse.method_internal')}",
                     [("Voltar", "Secondary.TButton", self._back_to_results)])

    def _back_to_results(self) -> None:
        self.show("results")
        self._footer("", [("Voltar", "Secondary.TButton",
                           lambda: self.show("disks"))])

    # ------------------------------------------------------------------
    # 6. Recuperar
    # ------------------------------------------------------------------
    def _build_recover(self) -> None:
        screen = Screen(self)
        self.screens["recover"] = screen
        tk.Label(screen, text=t("gui.recover.title"), font=(self.family, 18, "bold"),
                 bg=COLORS["background"], fg=COLORS["text"]).pack(anchor="w", padx=28, pady=(24, 2))
        tk.Label(screen, text=t("gui.recover.subtitle"), font=(self.family, 10),
                 bg=COLORS["background"], fg=COLORS["text_muted"]).pack(anchor="w", padx=28)

        card = tk.Frame(screen, bg=COLORS["surface"])
        card.pack(fill="x", padx=28, pady=20)
        tk.Label(card, text=t("gui.recover.what"), font=(self.family, 11, "bold"),
                 bg=COLORS["surface"], fg=COLORS["text"]).pack(anchor="w", padx=18, pady=(16, 6))
        for index, step in enumerate(("gui.recover.step1", "gui.recover.step2",
                                      "gui.recover.step3")):
            tk.Label(card, text="•  " + t(step), font=(self.family, 10),
                     bg=COLORS["surface"], fg=COLORS["text"], anchor="w",
                     justify="left").pack(anchor="w", padx=36, pady=3)

        self.backup_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(card, text=t("gui.recover.backup"), variable=self.backup_var,
                        style="TCheckbutton").pack(anchor="w", padx=18, pady=(14, 16))

        self.recover_detail = tk.Label(screen, text="", font=(self.family, 10),
                                       bg=COLORS["background"], fg=COLORS["text_muted"],
                                       wraplength=760, justify="left", anchor="w")
        self.recover_detail.pack(anchor="w", padx=28, pady=(0, 10))

    def _on_recover(self) -> None:
        if self.selected is None:
            return
        self.show("recover")
        detail = (f"{self.selected.fs_type.upper()}  ·  "
                  f"setor {self.selected.start_sector}  ·  "
                  f"{format_size(self.selected.size_bytes)}")
        self.recover_detail.configure(text=detail)
        self._footer("", [
            (t("gui.recover.cancel"), "Secondary.TButton", self._back_to_results),
            (t("gui.recover.confirm"), "Primary.TButton", self._do_recover),
        ])

    def _do_recover(self) -> None:
        if self.selected is None:
            return
        candidate = self.selected
        try:
            device = open_device(self.device_spec or "", read_only=False)
        except Exception as exc:
            self._show_error(str(exc))
            return
        try:
            table = load_partition_table(device)
            if table is None:
                raise LostPartError(t("error.no_table"))
            if self.backup_var.get():
                folder = Path.home() / "lostpart-backups"
                folder.mkdir(parents=True, exist_ok=True)
                import time
                stamp = time.strftime("%Y%m%d-%H%M%S")
                create_backup(device, table, folder / f"backup-{stamp}.json",
                              device_id=str(getattr(device, "path", "")))
            outcome = recover_partition(device, candidate, table, dry_run=False)
            self.done_message.configure(text=outcome.message)
        except Exception as exc:
            self._show_error(str(exc))
            return
        finally:
            device.close()
        self.show("done")
        self._footer("", [(t("gui.recover.done.close"), "Primary.TButton",
                           self.root.destroy)])

    def _show_error(self, message: str) -> None:
        from tkinter import messagebox

        messagebox.showerror(t("app.name"), message, parent=self.root)

    # ------------------------------------------------------------------
    # 7. Concluído
    # ------------------------------------------------------------------
    def _build_done(self) -> None:
        screen = Screen(self)
        self.screens["done"] = screen
        tk.Label(screen, text=t("gui.recover.done.title"), font=(self.family, 20, "bold"),
                 bg=COLORS["background"], fg=COLORS["success"]).pack(anchor="w", padx=28, pady=(28, 6))
        self.done_message = tk.Label(screen, text="", font=(self.family, 11),
                                      bg=COLORS["background"], fg=COLORS["text"],
                                      wraplength=760, justify="left", anchor="w")
        self.done_message.pack(anchor="w", padx=28, pady=(0, 18))

        card = tk.Frame(screen, bg=COLORS["info_soft"])
        card.pack(fill="x", padx=28)
        tk.Label(card, text=t("gui.recover.done.next"), font=(self.family, 11, "bold"),
                 bg=COLORS["info_soft"], fg=COLORS["info"]).pack(anchor="w", padx=18, pady=(14, 4))
        tk.Label(card, text=t("gui.recover.done.hint"), font=(self.family, 10),
                 bg=COLORS["info_soft"], fg=COLORS["text"], wraplength=740,
                 justify="left", anchor="w").pack(anchor="w", padx=18, pady=(0, 14))

    # ------------------------------------------------------------------
    # Aviso de permissões
    # ------------------------------------------------------------------
    def _build_admin_banner(self) -> tk.Frame:
        """Cria a faixa de aviso sobre permissões insuficientes."""
        bar = tk.Frame(self.root, bg=COLORS["warning_soft"])
        tk.Label(bar, text=t("gui.admin.title"), font=(self.family, 10, "bold"),
                 bg=COLORS["warning_soft"], fg=COLORS["warning"]).pack(side="left", padx=18, pady=10)
        tk.Label(bar, text=t("gui.admin.body"), font=(self.family, 9),
                 bg=COLORS["warning_soft"], fg=COLORS["text"]).pack(side="left", pady=10)
        ttk.Button(bar, text=t("gui.admin.elevate"),
                   style="Secondary.TButton",
                   command=self._elevate).pack(side="right", padx=18, pady=6)
        return bar

    def _show_admin_banner(self) -> None:
        """Mostra a faixa de permissões insuficientes."""
        self.admin_bar.grid()

    def _elevate(self) -> None:
        """Reabre o programa com privilégios de administrador."""
        try:
            if getattr(sys, "frozen", False):
                arguments = sys.argv[1:]
                executable = sys.executable
            else:
                arguments = ["-m", "lostpart.cli", "gui", *sys.argv[1:]]
                executable = sys.executable
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Start-Process", "-FilePath", f"'{executable}'",
                 "-ArgumentList", "'" + "','".join(arguments) + "'",
                 "-Verb", "RunAs"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                self.root.destroy()
        except Exception as exc:  # pragma: no cover - depends on the OS
            self._show_error(str(exc))

    def check_admin(self) -> bool:
        """True quando o programa já roda com privilégios suficientes."""
        from ..device import list_physical_device_specs

        try:
            specs = list_physical_device_specs()
        except Exception:
            self._show_admin_banner()
            return False
        if not specs:
            self._show_admin_banner()
            return False
        try:
            device = open_device(specs[0], read_only=True)
        except Exception:
            self._show_admin_banner()
            return False
        device.close()
        return True

    # ------------------------------------------------------------------
    def run(self) -> None:
        self.check_admin()
        self.root.mainloop()

    def destroy(self) -> None:
        self._closing = True
        self.root.destroy()


def run_gui(argv: list[str] | None = None) -> int:
    """Abre a interface gráfica."""
    try:
        app = LostPartApp()
    except Exception as exc:  # pragma: no cover - depends on the display
        print(f"Não foi possível abrir a interface gráfica: {exc}", file=sys.stderr)
        return 1
    app.run()
    return 0
