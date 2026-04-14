"""Waits for the database to become available and creates the database if it does not exist."""
import os
import sys
import time


def _wait_postgres(host: str, port: str, user: str, password: str, db_name: str) -> None:
    import psycopg2

    conn_kwargs = dict(host=host, port=int(port), user=user, password=password, dbname="postgres")
    max_attempts = 30
    for attempt in range(1, max_attempts + 1):
        try:
            conn = psycopg2.connect(**conn_kwargs, connect_timeout=5)
            conn.autocommit = True
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if not cursor.fetchone():
                cursor.execute(f'CREATE DATABASE "{db_name}"')
            conn.close()
            print(f"[wait_for_db] Database '{db_name}' is ready.", flush=True)
            return
        except psycopg2.OperationalError as e:
            print(f"[wait_for_db] Attempt {attempt}/{max_attempts} failed: {e}", flush=True)
            time.sleep(2)

    print("[wait_for_db] PostgreSQL not available after 60 seconds. Exiting.", flush=True)
    sys.exit(1)


def _wait_sqlserver(host: str, port: str, password: str, db_name: str) -> None:
    import pyodbc

    # Try ODBC Driver 18 first, fall back to 17
    drivers = pyodbc.drivers()
    if "ODBC Driver 18 for SQL Server" in drivers:
        driver = "ODBC Driver 18 for SQL Server"
    elif "ODBC Driver 17 for SQL Server" in drivers:
        driver = "ODBC Driver 17 for SQL Server"
    else:
        driver = drivers[0] if drivers else "SQL Server"

    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={host},{port};"
        f"UID=sa;"
        f"PWD={password};"
        f"TrustServerCertificate=yes"
    )

    max_attempts = 30
    for attempt in range(1, max_attempts + 1):
        try:
            conn = pyodbc.connect(conn_str, autocommit=True, timeout=5)
            cursor = conn.cursor()
            cursor.execute(
                f"IF NOT EXISTS (SELECT * FROM sys.databases WHERE name = N'{db_name}') "
                f"CREATE DATABASE [{db_name}]"
            )
            conn.close()
            print(f"[wait_for_db] Database '{db_name}' is ready.", flush=True)
            return
        except pyodbc.Error as e:
            print(f"[wait_for_db] Attempt {attempt}/{max_attempts} failed: {e}", flush=True)
            time.sleep(2)

    print("[wait_for_db] SQL Server not available after 60 seconds. Exiting.", flush=True)
    sys.exit(1)


def wait_and_create() -> None:
    db_type = os.getenv("DB_TYPE", "postgres").lower()
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432" if db_type == "postgres" else "1433")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "postgres")
    db_name = os.getenv("DB_NAME", "swagger_agent")

    if db_type == "sqlserver":
        _wait_sqlserver(host, port, password, db_name)
    else:
        _wait_postgres(host, port, user, password, db_name)


if __name__ == "__main__":
    wait_and_create()
