#!/usr/bin/env python3
import os
import sys

# Entrypoint executed when Railway uses Railpack Python auto-detect
if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    entrypoint = os.path.join(script_dir, "deploy", "ogx", "entrypoint.sh")
    if not os.path.exists(entrypoint):
        entrypoint = "/app/entrypoint.sh"

    if os.path.exists(entrypoint):
        os.chmod(entrypoint, 0o755)
        os.execv("/bin/bash", ["/bin/bash", entrypoint])
    else:
        print(f"ERROR: Cannot find entrypoint script at {entrypoint}", file=sys.stderr)
        sys.exit(1)
