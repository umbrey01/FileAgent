import tkinter as tk
from app.gui import FileAgentApp
from app.db import init_db  # 1. 确保这里导入了 init_db

if __name__ == "__main__":
    init_db()  # 2. 确保启动时调用了它！
    root = tk.Tk()
    app = FileAgentApp(root)
    root.mainloop()