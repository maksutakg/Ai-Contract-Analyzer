import argparse
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local yargi-mcp HTTP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    cmd = [
        "uvx",
        "--with",
        "mcp<1.26",
        "--with",
        "fastmcp<2.15",
        "--with",
        "uvicorn[standard]",
        "--from",
        "yargi-mcp",
        "uvicorn",
        "asgi_app:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())

