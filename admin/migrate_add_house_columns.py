# admin/migrate_add_house_columns.py
from models import get_db

def run():
    conn = get_db()
    try:
        # Add columns if they don't already exist
        for col in [
            ("ensuites_available", "INTEGER DEFAULT 0"),
            ("double_beds_available", "INTEGER DEFAULT 0"),
            ("couples_ok_available", "INTEGER DEFAULT 0"),
        ]:
            name, decl = col
            try:
                conn.execute(f"ALTER TABLE houses ADD COLUMN {name} {decl}")
                print(f"Added column {name}")
            except Exception as e:
                if "duplicate column" in str(e).lower():
                    print(f"Column {name} already exists, skipping")
                else:
                    raise
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    run()
