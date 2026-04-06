import sqlite3

conn = sqlite3.connect("voice_tasks.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY,
        user_id INTEGER
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        phrase TEXT,
        voice_id TEXT,
        approved INTEGER
    )
    """)

    conn.commit()