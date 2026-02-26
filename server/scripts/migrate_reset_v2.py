from server.db import get_conn, init_schema

def main():
    conn = get_conn()
    # Quick sanity check: if messages exists and has rows, abort
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()
        if row and int(row["c"]) > 0:
            raise SystemExit("Refusing reset: messages table has rows.")
    except Exception:
        pass
    conn.close()

    init_schema()
    print("DB schema reset/migrated to v2 successfully.")

if __name__ == "__main__":
    main()