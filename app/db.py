import sqlite3
from datetime import datetime

DB_NAME = "agent.db"

def init_db():
    """初始化数据库，建一张表存日志"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            action TEXT,
            status TEXT,
            detail TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def log_action(task_id: str, action: str, status: str, detail: str):
    """把一条动作记录写进"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO audit_logs (task_id, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
        (task_id, action, status, detail, now)
    )
    conn.commit()
    conn.close()