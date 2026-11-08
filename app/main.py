import tkinter as tk
from app.gui import FileAgentApp
from app.db import init_db

if __name__ == "__main__":
    init_db()
    root = tk.Tk()
    app = FileAgentApp(root)
    root.mainloop()