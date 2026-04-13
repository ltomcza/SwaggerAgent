"""Debug entry point: runs DB setup then starts uvicorn under debugpy."""
import subprocess
import sys

import uvicorn


def main() -> None:
    subprocess.run([sys.executable, "wait_for_db.py"], check=True)
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
