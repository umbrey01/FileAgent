from pathlib import Path

class PathViolation(Exception):
    pass

def _safe(root: Path, p: str) -> Path:
    target = (root / p).resolve()
    if not target.is_relative_to(root.resolve()):
        raise PathViolation(f"越界: {p}")
    return target


def list_files(root: Path, subdir: str = ".") -> list[dict]:
    base = _safe(root, subdir)
    files = []

    for f in base.rglob("*"):
        # 过滤掉系统回收站、隐藏文件等无关目录
        if "$recycle.bin" in str(f).lower() or "system volume information" in str(f).lower():
            continue

        if f.is_file() and not f.name.startswith("."):
            rel_path = f.relative_to(root)
            files.append({
                "name": str(rel_path).replace("\\", "/"),
                "size": f.stat().st_size
            })
    return files

def plan_move(root: Path, src: str, dst: str) -> dict:
    s, d = _safe(root, src), _safe(root, dst)
    if not s.exists():
        raise FileNotFoundError(src)
    if d.exists():
        raise FileExistsError(dst)   # 重名冲突
    return {"src": str(s), "dst": str(d)}

def execute_move(root: Path, src: str, dst: str) -> None:
    s, d = _safe(root, src), _safe(root, dst)
    d.parent.mkdir(parents=True, exist_ok=True)
    s.rename(d)