"""Waits for SQL Server to become available and creates the database if it does not exist."""
import os
import sys
import time

import pyodbc


def wait_and_create() -> None:
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "1433")
    password = os.getenv("DB_PASSWORD", "YourStrong!Passw0rd")
    db_name = os.getenv("DB_NAME", "swagger_agent")

    # Try ODBC Driver 18 first, fall back to 17
    import pyodbc as _pyodbc
    drivers = _pyodbc.drivers()
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


if __name__ == "__main__":
    wait_and_create()
