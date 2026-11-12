from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path


class PathViolation(Exception):
    pass


# 不进入的目录（按路径段匹配，不区分大小写）。按需自己增删。
IGNORED_DIR_NAMES = {
    # 版本控制 / 虚拟环境 / 依赖
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    # 编辑器与工具缓存
    ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    # 系统目录 / 回收站
    "$recycle.bin", "$recycler", "system volume information",
    "windows", "program files", "program files (x86)", "programdata",
}


def _ignore_oserror(_err: OSError) -> None:
    """os.walk 遇到无权限目录时跳过，而不是让整次扫描失败。"""
    return None


def _safe(root: Path, p: str) -> Path:
    """把相对/绝对路径约束在 root 之内。

    模型给出绝对路径（如 D:/proj/a.txt）时按绝对路径比较，
    不会再用 root / p 把左半边丢弃后误判为越界。
    """
    root = Path(root).resolve()
    raw = (p or "").strip() or "."
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    target = candidate.resolve()
    if target != root and not target.is_relative_to(root):
        raise PathViolation(f"越界: {p}")
    return target


def list_files(
    root: Path,
    subdir: str = ".",
    max_items: int = 3000,
    include_hidden: bool = False,
) -> list[dict]:
    """递归列出文件。有忽略规则、有数量上限、单文件失败不会中断整次扫描。"""
    root_r = Path(root).resolve()
    base = _safe(root_r, subdir)

    files: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(base, onerror=_ignore_oserror):
        # 原地剪枝：隐藏目录和忽略目录里的文件不会被列出来
        pruned = []
        for d in dirnames:
            if d.lower() in IGNORED_DIR_NAMES:
                continue
            if not include_hidden and d.startswith("."):
                continue
            pruned.append(d)
        dirnames[:] = pruned

        for name in filenames:
            if not include_hidden and name.startswith("."):
                continue
            full = Path(dirpath) / name
            try:
                st = full.stat()
            except OSError:
                continue
            try:
                rel = full.relative_to(root_r)
            except ValueError:
                continue
            try:
                mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")
            except (OSError, OverflowError, ValueError):
                mtime = "unknown"      # 时间戳损坏/超范围，不让整次扫描失败
            files.append({
                "name": rel.as_posix(),
                "size": st.st_size,
                "mtime": mtime,
                "ext": full.suffix.lower().lstrip("."),
            })
            if len(files) >= max_items:
                return files

    return files


def read_text_snippet(target: Path, limit: int = 500) -> str:
    """读文件开头的一小段文本，绝不整文件读入内存。

    编码按 UTF-8 -> GB18030 -> UTF-16(带 BOM) 依次尝试；二进制文件返回
    说明而不是抛异常；截断位置切断多字节字符时按本编码容错接受。
    """
    try:
        with open(target, "rb") as fh:
            raw = fh.read(8192)
        size = target.stat().st_size
    except OSError as e:
        return f"读取失败: {e}"

    if not raw:
        return "[空文件]"

    if b"\x00" in raw:
        # UTF-16 文本带 BOM，先排除这种"假二进制"
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            try:
                return raw.decode("utf-16", errors="replace")[:limit]
            except Exception:
                pass
        return f"[二进制文件，无法按文本读取] 大小 {size} 字节"

    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc, errors="strict")[:limit]
        except UnicodeDecodeError as e:
            # 出错位置贴着 8KB 边界 => 只是截断切断了字符，按本编码接受
            if e.start >= len(raw) - 3:
                return raw.decode(enc, errors="replace")[:limit]
            continue
    return raw.decode("utf-8", errors="replace")[:limit]


def plan_move(root: Path, src: str, dst: str) -> dict:
    s, d = _safe(root, src), _safe(root, dst)
    if not s.exists():
        raise FileNotFoundError(src)
    if d.exists():
        raise FileExistsError(dst)   # 重名冲突
    return {"src": str(s), "dst": str(d)}


def execute_move(root: Path, src: str, dst: str) -> None:
    s, d = _safe(root, src), _safe(root, dst)
    if not s.exists():
        raise FileNotFoundError(src)
    if d.exists():
        # 关键：shutil.move 的跨卷回退路径（copy2 + unlink）会静默覆盖同名文件
        raise FileExistsError(dst)
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
