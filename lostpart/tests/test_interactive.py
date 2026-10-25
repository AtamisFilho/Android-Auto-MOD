"""Tests for the interactive menu shown on a double click."""

from __future__ import annotations

from lostpart.interactive import _strip_bom, console_is_orphaned, run_interactive


def _answers(*values: str):
    """A replacement for ``input`` that answers the prompts in order.

    The "press Enter to return to the menu" prompts are confirmed with an
    empty line so that they do not consume one of the scripted answers.
    """
    queue = list(values)

    def _input(prompt: str = "") -> str:
        if "Press Enter to return" in prompt:
            return ""
        if not queue:
            return "0"
        return queue.pop(0)

    return _input


def test_the_byte_order_mark_is_removed_in_both_forms():
    assert _strip_bom("\ufeff0") == "0"
    assert _strip_bom("\u00ef\u00bb\u00bf0") == "0"
    assert _strip_bom("\ufeff\u00ef\u00bb\u00bf0") == "0"
    assert _strip_bom("0") == "0"
    assert _strip_bom("") == ""


def test_the_menu_lists_the_operations(capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", _answers("0"))
    assert run_interactive() == 0
    out = capsys.readouterr().out
    assert "lostpart" in out
    assert "List the disks" in out
    assert "Scan a disk for lost partitions" in out
    assert "Bye." in out


def test_the_menu_runs_the_listing(capsys, monkeypatch, tmp_path):
    from tests.fixtures import make_disk_with_ntfs

    image = tmp_path / "disk.img"
    image.write_bytes(make_disk_with_ntfs(total_sectors=8192, volume_start=4096))

    monkeypatch.setattr("builtins.input", _answers("1", str(image), "0"))
    assert run_interactive() == 0
    out = capsys.readouterr().out
    assert "MBR" in out
    assert "NTFS" in out


def test_the_menu_survives_a_failing_action(capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", _answers("2", "/definitely/not/a/device", "0"))
    assert run_interactive() == 0
    out = capsys.readouterr().out
    assert "error:" in out


def test_an_unknown_option_is_reported(capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", _answers("x", "0"))
    assert run_interactive() == 0
    out = capsys.readouterr().out
    assert "Unknown option" in out


def test_the_console_orphan_check_never_raises():
    assert isinstance(console_is_orphaned(), bool)


def test_the_cli_without_a_command_opens_the_menu(capsys, monkeypatch):
    from lostpart.cli import main

    monkeypatch.setattr("builtins.input", _answers("0"))
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "1) List the disks" in out
    assert "Bye." in out
