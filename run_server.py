#!/usr/bin/env python3
"""Start Jarvis web server — stable, no auto-reload."""

import os
import sys

os.environ["PYTHONUNBUFFERED"] = "1"

import uvicorn

if __name__ == "__main__":
    print("Starting Jarvis on http://127.0.0.1:8765 ...", flush=True)
    uvicorn.run(
        "jarvis.api.server:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
        log_level="info",
    )
