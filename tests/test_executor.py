"""app/executor.py 的测试：执行层不依赖任何 UI，可以单独验证。"""

from pathlib import Path

from app.executor import run_moves


def _make_files(tmp_path: Path, names: list[str]) -> list[dict]:
    items = []
    for name in names:
        (tmp_path / name).write_text("x", encoding="utf-8")
        items.append({"src": name, "dst": f"out/{name}"})
    return items


def test_run_moves_moves_all(tmp_path):
    items = _make_files(tmp_path, ["a.txt", "b.txt"])

    result = run_moves(tmp_path, items, progress_every=1)

    assert result == {"total": 2, "done": 2, "failed": 0, "interrupted": False}
    assert (tmp_path / "out" / "a.txt").exists()
    assert (tmp_path / "out" / "b.txt").exists()
    assert not (tmp_path / "a.txt").exists()


def test_run_moves_reports_missing_source(tmp_path):
    errors = []
    result = run_moves(
        tmp_path,
        [{"src": "nope.txt", "dst": "out/nope.txt"}],
        on_error=lambda item, err: errors.append(item["src"]),
    )

    assert result["failed"] == 1
    assert result["done"] == 0
    assert errors == ["nope.txt"]


def test_run_moves_interrupts_between_files(tmp_path):
    items = _make_files(tmp_path, ["a.txt", "b.txt", "c.txt"])
    calls = {"n": 0}

    def should_continue():
        calls["n"] += 1
        return calls["n"] <= 1

    result = run_moves(tmp_path, items, should_continue=should_continue)

    assert result["interrupted"] is True
    assert result["done"] == 1
    assert (tmp_path / "out" / "a.txt").exists()
    assert not (tmp_path / "out" / "b.txt").exists()


def test_run_moves_emits_progress(tmp_path):
    items = _make_files(tmp_path, ["a.txt", "b.txt"])
    seen = []

    run_moves(tmp_path, items, on_progress=lambda *args: seen.append(args), progress_every=1)

    assert seen[-1] == (2, 2, 2, 0)


def test_run_moves_never_overwrites(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "a.txt").write_text("existing", encoding="utf-8")
    (tmp_path / "a.txt").write_text("new", encoding="utf-8")

    result = run_moves(tmp_path, [{"src": "a.txt", "dst": "out/a.txt"}])

    assert result["failed"] == 1
    assert (tmp_path / "out" / "a.txt").read_text(encoding="utf-8") == "existing"
    assert (tmp_path / "a.txt").exists()      # 源文件原地不动
