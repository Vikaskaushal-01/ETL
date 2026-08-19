import sqlite3

conn = sqlite3.connect("agentic_ai_etl.db")
cursor = conn.cursor()

try:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print("Tables:", tables)
    
    for table in tables:
        tname = table[0]
        print(f"\n--- Columns in {tname} ---")
        cursor.execute(f"PRAGMA table_info({tname})")
        print(cursor.fetchall())
        
        print(f"\n--- Data in {tname} (first 5 rows) ---")
        cursor.execute(f"SELECT * FROM {tname} LIMIT 5")
        rows = cursor.fetchall()
        for r in rows:
            print(r)
except Exception as e:
    print("Error:", e)
finally:
    conn.close()
