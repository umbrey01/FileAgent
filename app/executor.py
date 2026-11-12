"""执行层：把计划里的移动动作批量落地，完全不依赖任何 UI。

这一层只做一件事：按顺序把 items 里的 move 应用到磁盘上，并通过回调
汇报进度、错误和中断。它不 import tkinter，因此可以被 GUI、CLI 或测试
直接调用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from app.tools import execute_move


def run_moves(
    root: Path,
    items: Iterable[dict],
    should_continue: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int, int, int], None] | None = None,
    on_error: Callable[[dict, Exception], None] | None = None,
    progress_every: int = 50,
) -> dict:
    """按顺序执行 items 里的 move。

    参数：
        root            路径围栏的根目录
        items           计划条目，需含 src / dst
        should_continue 每处理一个文件前调用一次，返回 False 则中断
        on_progress     (已处理, 总数, 成功数, 失败数)，每 progress_every 个及结束时回调
        on_error        (item, 异常)，单个文件失败时回调（失败不影响其余文件）
        progress_every  进度回调间隔

    返回：{"total": int, "done": int, "failed": int, "interrupted": bool}
    """
    item_list = list(items)
    total = len(item_list)
    done = 0
    failed = 0
    interrupted = False

    for idx, item in enumerate(item_list, 1):
        if should_continue is not None and not should_continue():
            interrupted = True
            break

        try:
            execute_move(root, item["src"], item["dst"])
            done += 1
        except Exception as e:          # 单个文件失败不影响其余文件
            failed += 1
            if on_error is not None:
                on_error(item, e)

        if on_progress is not None and (idx % progress_every == 0 or idx == total):
            on_progress(idx, total, done, failed)

    return {
        "total": total,
        "done": done,
        "failed": failed,
        "interrupted": interrupted,
    }
