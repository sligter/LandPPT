#!/usr/bin/env python3
"""
LandPPT Application Runner

This script starts the LandPPT FastAPI application with proper configuration.
"""

import uvicorn
import sys
import os
import asyncio
from dotenv import load_dotenv

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Load environment variables with error handling
try:
    load_dotenv()
except PermissionError as e:
    print(f"Warning: Could not load .env file due to permission error: {e}")
    print("Continuing with system environment variables...")
except Exception as e:
    print(f"Warning: Could not load .env file: {e}")
    print("Continuing with system environment variables...")

def main():
    """Main entry point for running the application"""

    # Get configuration from environment variables with defaults
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "true").lower() in ("true", "1", "yes", "on")
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    workers = int(os.getenv("WORKERS", "1"))

    # Uvicorn's multi-worker supervisor has a watchdog that can SIGTERM "unresponsive" workers.
    # Long-running background tasks (like video export) can temporarily block/slow the event loop,
    # so we use a higher default to avoid killing workers during heavy exports.
    try:
        timeout_worker_healthcheck = int(os.getenv("UVICORN_TIMEOUT_WORKER_HEALTHCHECK", "60"))
    except Exception:
        timeout_worker_healthcheck = 60
    timeout_worker_healthcheck = max(5, timeout_worker_healthcheck)

    # Workers and reload cannot be combined; prefer workers when explicitly set
    if workers > 1 and reload:
        reload = False

    # Configuration
    config = {
        "app": "landppt.main:app",
        "host": host,
        "port": port,
        "reload": reload,
        "log_level": log_level,
        "access_log": True,
        "timeout_worker_healthcheck": timeout_worker_healthcheck,
    }
    if workers > 1:
        config["workers"] = workers
    
    print("Starting LandPPT Server...")
    print(f"Host: {config['host']}")
    print(f"Port: {config['port']}")
    print(f"Reload: {config['reload']}")
    print(f"Log Level: {config['log_level']}")
    print(f"Workers: {config.get('workers', 1)}")
    print(f"Server will be available at: http://localhost:{config['port']}")
    print(f"Web Interface: http://localhost:{config['port']}/web")
    print("=" * 60)

    try:
        uvicorn.run(**config)
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Error starting server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
