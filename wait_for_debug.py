"""Wait for the debug container to be running and debugpy to be ready on port 5678."""
import socket
import subprocess
import sys
import time

CONTAINER = "swagger_agent_app"
HOST, PORT = "127.0.0.1", 5678
TIMEOUT = 300  # 5 minutes — Docker build from scratch can take a while


def container_is_running() -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", CONTAINER],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "true"
    except Exception:
        return False


def debugpy_is_ready() -> bool:
    try:
        socket.create_connection((HOST, PORT), 1).close()
        return True
    except OSError:
        return False


print(f"Waiting for container '{CONTAINER}' to start...", flush=True)
for _ in range(TIMEOUT):
    if container_is_running():
        break
    time.sleep(1)
else:
    print(f"ERROR: '{CONTAINER}' did not start within {TIMEOUT}s", file=sys.stderr)
    sys.exit(1)

print(f"Container running. Waiting for debugpy on {HOST}:{PORT}...", flush=True)
for _ in range(TIMEOUT):
    if debugpy_is_ready():
        # Double-check after a short pause to avoid Docker-proxy false positives
        time.sleep(0.5)
        if debugpy_is_ready():
            print("debugpy is ready — attaching now.", flush=True)
            sys.exit(0)
    time.sleep(1)

print(f"ERROR: debugpy not reachable on {HOST}:{PORT} after {TIMEOUT}s", file=sys.stderr)
sys.exit(1)
