"""针对搬进 app/tools.py 的读取/移动行为的补充测试。"""

import pytest

from app.tools import execute_move, read_text_snippet


def test_read_text_snippet_utf8(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("你好 hello", encoding="utf-8")

    assert read_text_snippet(p).startswith("你好")


def test_read_text_snippet_gb18030(tmp_path):
    p = tmp_path / "gbk.txt"
    p.write_bytes("中文内容".encode("gb18030"))

    assert "中文内容" in read_text_snippet(p)


def test_read_text_snippet_utf16_with_bom(tmp_path):
    p = tmp_path / "u16.txt"
    p.write_bytes("hello".encode("utf-16"))

    assert "hello" in read_text_snippet(p)


def test_read_text_snippet_binary(tmp_path):
    p = tmp_path / "b.bin"
    p.write_bytes(b"\x00\x01\x02\x03")

    assert "二进制" in read_text_snippet(p)


def test_read_text_snippet_empty(tmp_path):
    p = tmp_path / "e.txt"
    p.write_bytes(b"")

    assert "空文件" in read_text_snippet(p)


def test_read_text_snippet_respects_limit(tmp_path):
    p = tmp_path / "big.txt"
    p.write_bytes(b"a" * 100_000)

    assert len(read_text_snippet(p, limit=500)) == 500


def test_execute_move_refuses_existing_target(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_text("new", encoding="utf-8")
    (tmp_path / "sub" / "a.txt").write_text("old", encoding="utf-8")

    with pytest.raises(FileExistsError):
        execute_move(tmp_path, "a.txt", "sub/a.txt")

    assert (tmp_path / "sub" / "a.txt").read_text(encoding="utf-8") == "old"
    assert (tmp_path / "a.txt").exists()
