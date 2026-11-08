import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from app.agent import generate_plan
from app.tools import execute_move, PathViolation
import json
import os
from app.agent import generate_plan, get_models


class FileAgentApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("受限文件整理 Agent")
        self.root.geometry("750x550")

        self.current_dir = None
        self.current_plan = []

        # ================= 1. 先把底部的日志框建出来 =================
        log_frame = tk.Frame(root)
        log_frame.pack(side="bottom", fill="x", padx=10, pady=5)
        tk.Label(log_frame, text="运行日志:").pack(anchor="w")
        self.log_text = tk.Text(log_frame, height=5, state="disabled", bg="#f0f0f0")
        self.log_text.pack(fill="x")

        # 底部按钮
        bottom_frame = tk.Frame(root, pady=5)
        bottom_frame.pack(side="bottom", fill="x", padx=10)
        tk.Button(bottom_frame, text="批准并执行", bg="lightgreen", command=self.execute_plan).pack(side="left")

        # ================= 2. 加载配置与 API 面板 =================
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

        tk.Button(api_frame, text="刷新模型列表", command=self.refresh_models).grid(row=1, column=2, columnspan=2,
                                                                                    pady=2)

        # 现在这里有 log_text 了，可以放心调用自动拉取
        if self.config.get("api_key") and self.config.get("base_url"):
            self.refresh_models()
            self.model_combo.set(self.config.get("model_name", ""))

        # ================= 3. 顶部选择目录与指令 =================
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
        tk.Button(mid_frame, text="生成方案", command=self.make_plan).pack(side="left", padx=10)

        # ================= 4. 中间的表格 =================
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

        # 保存配置
        self.save_config()

        for item in self.tree.get_children():
            self.tree.delete(item)

        instruction = self.instruction_entry.get()
        self.log(f"正在生成方案，指令: {instruction}, 模型: {model_name}")

        try:
            # 传入新的参数
            self.current_plan = generate_plan(self.current_dir, instruction, api_key, base_url, model_name)
            for item in self.current_plan:
                display_action = item["action"]
                display_reason = item["reason"]
                if item.get("status") == "error":
                    display_action = "🚫 拦截"

                self.tree.insert("", "end", values=(item["src"], item["dst"], display_action, display_reason))

            self.log(f"方案生成完毕，共 {len(self.current_plan)} 个文件。")
        except Exception as e:
            self.log(f"生成方案出错: {e}")
            messagebox.showerror("错误", str(e))

    def execute_plan(self) -> None:
        if not self.current_plan:
            messagebox.showwarning("提示", "当前没有方案，请先生成")
            return

        if not messagebox.askyesno("确认", "确定要执行这个整理方案吗？"):
            return

        success_count = 0
        for item in self.current_plan:
            if item["action"] == "move" and item.get("status") == "ok":
                # =============== 关键防御：执行前二次确认文件存在 ===============
                src_path = self.current_dir / item["src"]
                if not src_path.exists():
                    self.log(f"⚠️ 跳过 {item['src']}：文件已被手动删除或移动")
                    continue
                # ==================================================================

                try:
                    execute_move(self.current_dir, item["src"], item["dst"])
                    success_count += 1
                except Exception as e:
                    self.log(f"移动 {item['src']} 失败: {e}")
            elif item.get("status") == "error":
                self.log(f"跳过 {item['src']}：{item.get('reason')}")

        self.log(f"执行完毕，成功移动 {success_count} 个文件。")
        messagebox.showinfo("完成", f"成功移动 {success_count} 个文件！")
        self.current_plan = []
        for item in self.tree.get_children():
            self.tree.delete(item)

    def load_config(self) -> dict:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_config(self) -> None:
        config = {
            "base_url": self.url_entry.get().strip(),
            "api_key": self.key_entry.get().strip(),
            "model_name": self.model_combo.get().strip()
        }
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config, f)

    def refresh_models(self) -> None:
        key = self.key_entry.get().strip()
        url = self.url_entry.get().strip()
        if not key or not url:
            messagebox.showwarning("提示", "请先填写 Base URL 和 API Key")
            return

        self.log("正在获取模型列表...")
        models = get_models(key, url)
        if models:
            self.model_combo["values"] = models
            # 如果当前没有选择，默认选第一个
            if not self.model_combo.get() and models:
                # 优先选 deepseek-chat 或 gpt-3.5-turbo 之类的常用模型
                default_model = models[0]
                for m in models:
                    if "deepseek-chat" in m or "gpt-4o-mini" in m or "gpt-3.5" in m:
                        default_model = m
                        break
                self.model_combo.set(default_model)
            self.log(f"成功获取 {len(models)} 个模型")
        else:
            self.log("获取模型失败，请检查 Key 或 URL 是否正确")