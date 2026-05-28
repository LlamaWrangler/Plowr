"""
Entry point for the GPV (Gross Premium Valuation) system.

Usage:
  python main.py                  # Start web server on port 8000
  python main.py --port 9000      # Custom port
  python -m gpv.mcp_server        # Start MCP server (stdio transport)
"""
import argparse
import sys
from pathlib import Path

# Ensure the project root is importable
sys.path.insert(0, str(Path(__file__).parent))

from gpv import storage


def init_data():
    """Seed client data from the sample CSV on first run."""
    clients = storage.load_clients()
    if not clients:
        sample_csv = Path(__file__).parent / "gpv" / "data" / "clients" / "sample_clients.csv"
        if sample_csv.exists():
            clients = storage.load_clients_from_csv(sample_csv.read_text())
            storage.save_clients(clients)
            print(f"[GPV] Seeded {len(clients)} sample clients from CSV.")


def run_web(port: int, host: str):
    import uvicorn
    from gpv.api import app
    init_data()
    print(f"[GPV] Web UI → http://{host}:{port}")
    print(f"[GPV] API docs → http://{host}:{port}/docs")
    print(f"[GPV] MCP server → run: python -m gpv.mcp_server")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GPV System")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    run_web(args.port, args.host)
