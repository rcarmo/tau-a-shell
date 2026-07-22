from pathlib import Path

from tau_coding.tui.file_drop import normalize_dropped_paths


def test_normalize_dropped_paths_quotes_spaces(tmp_path: Path) -> None:
    path = tmp_path / "file name.txt"
    path.write_text("hello", encoding="utf-8")

    assert normalize_dropped_paths(str(path)) == f'"{path}"'


def test_normalize_dropped_paths_accepts_file_uri(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("hello", encoding="utf-8")

    assert normalize_dropped_paths(path.as_uri()) == str(path)


def test_normalize_dropped_paths_rejects_non_paths() -> None:
    assert normalize_dropped_paths("please read /tmp/maybe") is None
