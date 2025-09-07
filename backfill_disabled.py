from db import get_db
from utils_summaries import recompute_all_houses_disabled

if __name__ == "__main__":
    conn = get_db()
    n = recompute_all_houses_disabled(conn)
    conn.close()
    print(f"Updated {n} houses with disabled rollups")
