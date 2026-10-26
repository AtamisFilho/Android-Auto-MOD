"""Tests for the pt-BR catalogue, the console renderer and the GUI.

The GUI tests are skipped when there is no display available, so the suite
still runs on a headless build server.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout

import pytest

from lostpart.i18n import MESSAGES, format_size, sector_number, t
from lostpart.scan.model import LostPartitionCandidate
from lostpart.ui import console


# ----------------------------------------------------------------------
# i18n
# ----------------------------------------------------------------------


def test_every_message_is_in_brazilian_portuguese():
    """No message may be left in English."""
    english = ("the ", "disk", "partition", "sector", "file", "not ", "error")
    offenders = []
    for key, text in MESSAGES.items():
        if not isinstance(text, str):
            continue
        lowered = text.lower()
        if lowered.startswith(english) or lowered.endswith(("the candidate", "error")):
            offenders.append(key)
    assert offenders == [], f"mensagens ainda em inglês: {offenders}"


def test_unknown_key_returns_the_key_itself():
    assert t("no.such.key") == "no.such.key"


def test_message_is_formatted_with_its_arguments():
    assert t("error.overlap", index=2, start=10, end=20) == (
        "A partição candidata sobrepõe a partição 2 (setores 10 a 20)."
    )


def test_a_missing_argument_does_not_raise():
    assert t("error.overlap") == MESSAGES["error.overlap"]


def test_format_size_uses_binary_units():
    assert format_size(0) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1024 * 1024) == "1.0 MB"
    assert format_size(1024 ** 3) == "1.0 GB"
    assert format_size(1024 ** 4) == "1.0 TB"


def test_sector_number_is_pulled_out_of_a_progress_message():
    assert sector_number("scanning sector 1048576") == "1048576"
    assert sector_number("scanning sector: 42") == "42"
    assert sector_number("nothing here") == "nothing here"


# ----------------------------------------------------------------------
# console
# ----------------------------------------------------------------------


def _render(function, *args, **kwargs) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        function(*args, **kwargs)
    return buffer.getvalue()


def test_table_aligns_the_columns():
    text = _render(
        console.table,
        ("Início", "Tamanho"),
        [["2048", "128.0 MB"], ["1048576", "1.0 GB"]],
        ("right", "right"),
    )
    lines = text.splitlines()
    assert lines[0].split() == ["Início", "Tamanho"]
    # As colunas da direita terminam sempre na mesma posicao, entao todas as
    # linhas têm o mesmo comprimento.
    assert len(lines[0]) == len(lines[2]) == len(lines[3])


def test_table_without_rows_says_so():
    assert "(nenhum resultado)" in _render(console.table, ("A",), [])


def test_panel_draws_a_closed_box():
    text = _render(console.panel, "Título", ["linha um"])
    lines = text.splitlines()
    assert lines[0].startswith("╭")
    assert lines[0].endswith("╮")
    assert lines[-1].startswith("╰")
    assert lines[-1].endswith("╯")
    assert "Título" in lines[1]
    assert "linha um" in lines[2]


def test_key_values_aligns_the_labels():
    text = _render(console.key_values, [("Disco", "\\\\.\\PhysicalDrive0"),
                                        ("Tabela", "GPT")])
    lines = text.splitlines()
    assert lines[0].index("\\\\.\\PhysicalDrive0") == lines[1].index("GPT")


def test_progress_bar_is_clamped_between_zero_and_one():
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        console.progress(-5.0)
        console.progress(5.0)
    written = buffer.getvalue()
    assert "  0.0%" in written
    assert "100.0%" in written


def test_setup_console_is_idempotent():
    console.setup_console()
    console.setup_console()


# ----------------------------------------------------------------------
# candidate model
# ----------------------------------------------------------------------


def test_candidate_size_is_reported_in_bytes():
    candidate = LostPartitionCandidate(
        start_sector=2048, sector_count=1024, fs_type="ntfs", label="NTFS",
        confidence=0.9,
    )
    assert candidate.size_bytes == 1024 * 512
    assert candidate.end_sector == 3072


def test_candidate_size_follows_the_sector_size():
    candidate = LostPartitionCandidate(
        start_sector=2048, sector_count=1024, fs_type="ntfs", label="NTFS",
        confidence=0.9, sector_size=4096,
    )
    assert candidate.size_bytes == 1024 * 4096


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    """Creates the window, or skips the test when there is no display."""
    pytest.importorskip("tkinter")
    from lostpart.ui.app import LostPartApp

    try:
        instance = LostPartApp()
    except Exception as exc:  # pragma: no cover - depends on the display
        pytest.skip(f"sem display disponível: {exc}")
    instance.root.update()
    yield instance
    instance.destroy()


def test_the_window_is_created(app):
    assert app.root.title().startswith("lostpart")
    assert app.root.winfo_width() > 0


def test_every_screen_of_the_assistant_exists(app):
    for name in ("welcome", "disks", "scan", "results", "preview", "recover", "done"):
        assert name in app.screens


def test_the_assistant_can_move_between_the_screens(app):
    for name in ("disks", "scan", "results", "preview", "recover", "done", "welcome"):
        app.show(name)
        app.root.update()
        assert app.current is app.screens[name]


def test_the_results_screen_lists_the_candidates(app):
    app.candidates = [
        LostPartitionCandidate(
            start_sector=2048, sector_count=1024, fs_type="ntfs", label="NTFS",
            confidence=0.9,
        )
    ]
    app._fill_results()
    app.root.update()
    children = app.result_tree.get_children()
    assert len(children) == 1
    values = app.result_tree.item(children[0], "values")
    assert values[0] == "setor 2048"
    assert values[1] == "512.0 KB"
    assert values[2] == "NTFS"


def test_the_results_screen_says_when_nothing_was_found(app):
    app.candidates = []
    app._fill_results()
    app.root.update()
    assert app.result_tree.get_children() == ()


def test_the_admin_banner_can_be_shown_and_hidden(app):
    app._show_admin_banner()
    app.root.update()
    assert app.admin_bar.winfo_ismapped()
    app.admin_bar.grid_remove()
    app.root.update()
    assert not app.admin_bar.winfo_ismapped()


def test_the_footer_is_rebuilt_on_demand(app):
    app._footer("dica", [("Ir", "Primary.TButton", lambda: None)])
    app.root.update()
    assert any(isinstance(child, type(app.hint)) for child in app.footer.winfo_children())
