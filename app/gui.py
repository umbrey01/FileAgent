import json
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.agent import (
    ACTION_MOVE,
    STATUS_CONFLICT,
    STATUS_ERROR,
    STATUS_OK,
    generate_plan,
    get_models,
    pick_default_model,
)
from app.executor import run_moves


class FileAgentApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("受限文件整理 Agent")
        self.root.geometry("750x550")

        self.current_dir = None
        self.current_plan = []
        self.plan_root = None      # 方案生成时的根目录，执行时必须沿用
        self._running = False      # 是否有执行任务在跑

        log_frame = tk.Frame(root)
        log_frame.pack(side="bottom", fill="x", padx=10, pady=5)
        tk.Label(log_frame, text="运行日志:").pack(anchor="w")
        self.log_text = tk.Text(log_frame, height=5, state="disabled", bg="#f0f0f0")
        self.log_text.pack(fill="x")

        # 底部按钮
        bottom_frame = tk.Frame(root, pady=5)
        bottom_frame.pack(side="bottom", fill="x", padx=10)
        self.btn_exec = tk.Button(bottom_frame, text="批准并执行", bg="lightgreen",
                                  command=self.execute_plan)
        self.btn_exec.pack(side="left")

        self.config_file = "config.json"
        self.config = self.load_config()

        api_frame = tk.LabelFrame(root, text="API 设置 (自动保存)", pady=5, padx=5)
        api_frame.pack(fill="x", padx=10, pady=5)

        tk.Label(api_frame, text="Base URL:").grid(row=0, column=0, sticky="e")
        self.url_entry = tk.Entry(api_frame, width=35)
        self.url_entry.insert(0, self.config.get("base_url", "https://api.deepseek.com"))
        self.url_entry.grid(row=0, column=1, padx=5, pady=2)

        tk.Label(api_frame, text="API Key:").grid(row=0, column=2, sticky="e")
        self.key_entry = tk.Entry(api_frame, width=35, show="*")
        self.key_entry.insert(0, self.config.get("api_key", ""))
        self.key_entry.grid(row=0, column=3, padx=5, pady=2)

        tk.Label(api_frame, text="模型:").grid(row=1, column=0, sticky="e")
        self.model_combo = ttk.Combobox(api_frame, width=32)
        self.model_combo.grid(row=1, column=1, padx=5, pady=2)

        tk.Button(api_frame, text="刷新模型列表", command=self.refresh_models).grid(
            row=1, column=2, columnspan=2, pady=2)

        # 先显示已保存的模型，再异步刷新列表，避免启动时卡住窗口
        if self.config.get("api_key") and self.config.get("base_url"):
            self.model_combo.set(self.config.get("model_name", ""))
            self.root.after(200, self.refresh_models)

        top_frame = tk.Frame(root, pady=10)
        top_frame.pack(fill="x", padx=10)
        tk.Button(top_frame, text="选择要整理的文件夹", command=self.select_dir).pack(side="left")
        self.dir_label = tk.Label(top_frame, text="未选择目录", fg="gray")
        self.dir_label.pack(side="left", padx=10)

        mid_frame = tk.Frame(root, pady=5)
        mid_frame.pack(fill="x", padx=10)
        tk.Label(mid_frame, text="指令：").pack(side="left")
        self.instruction_entry = tk.Entry(mid_frame, width=60)
        self.instruction_entry.insert(0, "把所有的 txt 文件整理一下")
        self.instruction_entry.pack(side="left", padx=5)
        self.btn_plan = tk.Button(mid_frame, text="生成方案", command=self.make_plan)
        self.btn_plan.pack(side="left", padx=10)

        self.tree = ttk.Treeview(root, columns=("src", "dst", "action", "reason"), show="headings")
        self.tree.heading("src", text="源文件")
        self.tree.heading("dst", text="目标路径")
        self.tree.heading("action", text="动作")
        self.tree.heading("reason", text="备注")
        self.tree.column("src", width=150)
        self.tree.column("dst", width=200)
        self.tree.column("action", width=80)
        self.tree.column("reason", width=150)
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 基础 ----------
    def log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def select_dir(self):
        directory = filedialog.askdirectory()
        if directory:
            self.current_dir = Path(directory)
            self.dir_label.config(text=str(self.current_dir), fg="black")
            self.log(f"已选择目录: {self.current_dir}")

    def _on_close(self) -> None:
        if self._running:
            if not messagebox.askyesno(
                "确认", "任务正在执行，强行关闭会中断并留下未完成的移动。确定退出吗？"
            ):
                return
        self._running = False
        self.root.destroy()

    # ---------- 生成方案（后台线程，不卡界面） ----------
    def make_plan(self) -> None:
        if not self.current_dir:
            messagebox.showwarning("提示", "请先选择文件夹")
            return

        api_key = self.key_entry.get().strip()
        base_url = self.url_entry.get().strip()
        model_name = self.model_combo.get().strip()
        if not api_key or not model_name:
            messagebox.showwarning("提示", "请先在顶部配置 API Key 并选择模型")
            return

        self.save_config()
        for item in self.tree.get_children():
            self.tree.delete(item)

        instruction = self.instruction_entry.get()
        plan_root = self.current_dir
        self.plan_root = plan_root
        self.log(f"正在生成方案，指令: {instruction}, 模型: {model_name}")

        self.btn_plan.config(state="disabled")
        self.btn_exec.config(state="disabled")

        def worker():
            try:
                plan = generate_plan(plan_root, instruction, api_key, base_url, model_name)
            except Exception as e:
                self.root.after(0, lambda err=e: self._on_plan_failed(err))
            else:
                self.root.after(0, lambda: self._on_plan_ready(plan))

        threading.Thread(target=worker, daemon=True).start()

    def _on_plan_ready(self, plan) -> None:
        self.current_plan = plan
        for item in plan:
            status = item.get("status")
            action = item.get("action", ACTION_MOVE)
            reason = item.get("reason", "")
            if status == STATUS_ERROR:
                action = "🚫 拦截"
            elif status == STATUS_CONFLICT:
                action = "⚠️ 冲突"
            self.tree.insert("", "end",
                             values=(item.get("src", ""), item.get("dst", ""), action, reason))

        ok = sum(1 for i in plan if i.get("status") == STATUS_OK)
        conflict = sum(1 for i in plan if i.get("status") == STATUS_CONFLICT)
        bad = sum(1 for i in plan if i.get("status") == STATUS_ERROR)
        self.log(f"方案生成完毕：可执行 {ok}，冲突 {conflict}，拦截 {bad}，共 {len(plan)} 条。")
        self.btn_plan.config(state="normal")
        self.btn_exec.config(state="normal")

    def _on_plan_failed(self, err) -> None:
        self.log(f"生成方案出错: {err}")
        messagebox.showerror("错误", str(err))
        self.btn_plan.config(state="normal")
        self.btn_exec.config(state="normal")

    # ---------- 执行方案（后台线程 + 进度 + 可中断） ----------
    def execute_plan(self) -> None:
        if not self.current_plan:
            messagebox.showwarning("提示", "当前没有方案，请先生成")
            return
        if not self.plan_root:
            messagebox.showwarning("提示", "方案没有记录根目录，请重新生成方案")
            return
        if self._running:
            messagebox.showwarning("提示", "已有任务正在执行")
            return

        todo = [i for i in self.current_plan
                if i.get("status") == STATUS_OK and i.get("action") == ACTION_MOVE]
        if not todo:
            messagebox.showinfo("提示", "没有可执行的动作（全部被拦截或冲突）")
            return

        if not messagebox.askyesno("确认", f"将移动 {len(todo)} 个文件，此操作不可自动撤销。确定执行吗？"):
            return

        plan_root = self.plan_root
        self._running = True
        self.btn_plan.config(state="disabled")
        self.btn_exec.config(state="disabled")
        self.log(f"开始执行，共 {len(todo)} 个文件...")

        def worker():
            # 执行编排全部在 app/executor.py，这里只负责把回调转成界面动作
            def on_error(item, err):
                self.root.after(0, lambda: self.log(f"移动 {item['src']} 失败: {err}"))

            def on_progress(idx, total, done, failed):
                self.root.after(0, lambda: self.log(
                    f"进度 {idx}/{total}（成功 {done}，失败 {failed}）"))

            result = run_moves(
                plan_root,
                todo,
                should_continue=lambda: self._running,
                on_progress=on_progress,
                on_error=on_error,
            )
            self.root.after(0, lambda: self._on_execute_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_execute_done(self, result: dict) -> None:
        self._running = False
        total = result["total"]
        done = result["done"]
        failed = result["failed"]

        if result["interrupted"]:
            self.log(f"执行被中断：已处理 {done + failed}/{total}（成功 {done}，失败 {failed}），"
                     f"剩余文件保持原样。")
            messagebox.showwarning(
                "已中断",
                f"执行被中断。\n已处理 {done + failed}/{total} 个文件"
                f"（成功 {done}，失败 {failed}）。\n剩余文件保持原样，重新生成方案可继续。"
            )
        else:
            self.log(f"执行完毕，成功 {done} 个，失败 {failed} 个。")
            messagebox.showinfo("完成", f"成功移动 {done} 个文件，失败 {failed} 个。")

        self.current_plan = []
        self.plan_root = None
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.btn_plan.config(state="normal")
        self.btn_exec.config(state="normal")

    # ---------- 配置 ----------
    def load_config(self) -> dict:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_config(self) -> None:
        config = {
            "base_url": self.url_entry.get().strip(),
            "api_key": self.key_entry.get().strip(),
            "model_name": self.model_combo.get().strip(),
        }
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config, f)

    # ---------- 模型列表（后台线程，启动不卡） ----------
    def refresh_models(self) -> None:
        key = self.key_entry.get().strip()
        url = self.url_entry.get().strip()
        if not key or not url:
            messagebox.showwarning("提示", "请先填写 Base URL 和 API Key")
            return

        self.log("正在获取模型列表...")

        def worker():
            models = get_models(key, url)
            self.root.after(0, lambda: self._on_models_ready(models))

        threading.Thread(target=worker, daemon=True).start()

    def _on_models_ready(self, models) -> None:
        if not models:
            self.log("获取模型失败，请检查 Key 或 URL 是否正确")
            return
        self.model_combo["values"] = models
        if not self.model_combo.get():
            self.model_combo.set(pick_default_model(models))
        self.log(f"成功获取 {len(models)} 个模型")
