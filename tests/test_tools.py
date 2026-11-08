import pytest
from pathlib import Path
from app.tools import list_files, execute_move, PathViolation

def test_list_files(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    assert len(list_files(tmp_path)) == 1

def test_path_violation(tmp_path):
    with pytest.raises(PathViolation):
        list_files(tmp_path, "../..")

def test_execute_move(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    execute_move(tmp_path, "a.txt", "sub/a.txt")
    assert (tmp_path / "sub/a.txt").exists()
    assert not (tmp_path / "a.txt").exists()git add .