"""Wait for the Postgres container to be ready.

Called by: just wait-db  →  uv run python scripts/wait_db.py
Works on Windows, macOS, and Linux without any shell-specific syntax.
"""

import subprocess
import sys
import time

TIMEOUT = 30
CMD = ["docker", "compose", "exec", "-T", "db", "pg_isready", "-U", "postgres"]


def main() -> None:
    print("Waiting for postgres…")
    for _ in range(TIMEOUT):
        result = subprocess.run(CMD, capture_output=True)
        if result.returncode == 0:
            print("Postgres is ready.")
            return
        time.sleep(1)

    print(f"Postgres did not become ready after {TIMEOUT}s.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
