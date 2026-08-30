"""FastAPI server for OpenAlex Local with full-text search.

Provides HTTP relay server for remote database access.

Usage:
    openalex-local relay                    # Run on default port 31292
    openalex-local relay --port 8080        # Custom port

    # Or directly:
    uvicorn openalex_local.server:app --host 0.0.0.0 --port 31292
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__
from .routes import router

# Create FastAPI app
app = FastAPI(
    title="OpenAlex Local API",
    description="Fast full-text search across 284M+ scholarly works",
    version=__version__,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)


@app.get("/")
def root():
    """API root with endpoint information."""
    return {
        "name": "OpenAlex Local API",
        "version": __version__,
        "status": "running",
        "endpoints": {
            "health": "/health",
            "info": "/info",
            "search": "/works?q=<query>",
            "get_by_id": "/works/{id_or_doi}",
            "batch": "/works/batch",
        },
    }


@app.get("/health")
def health():
    """Health check endpoint."""
    from .._core.db import get_db

    try:
        db = get_db()
        return {
            "status": "healthy",
            "database_connected": db is not None,
            "database_dsn": db.dsn if db else None,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


@app.get("/info")
def info():
    """Get database statistics."""
    from .._core.db import get_db

    try:
        db = get_db()
    except Exception as e:
        return {
            "name": "OpenAlex Local API",
            "version": __version__,
            "status": "error",
            "error": f"Database unavailable: {e}",
            "mode": "local",
            "total_works": 0,
            "fts_indexed": 0,
            "database_dsn": None,
        }

    # Recorded counters, not COUNT(*): a scan of 459M rows is too slow to serve
    # from an HTTP endpoint. They live in the build-metadata store now.
    work_count = 0
    fts_count = 0
    try:
        from .._core.state import get_metadata

        work_count = int(get_metadata("total_works") or 0)
        fts_count = int(get_metadata("fts_total_indexed") or 0)
    except Exception:
        pass  # never built, or the store is unreachable from here

    return {
        "name": "OpenAlex Local API",
        "version": __version__,
        "status": "running",
        "mode": "local",
        "total_works": work_count,
        "fts_indexed": fts_count,
        "database_dsn": db.dsn,
    }


# Default port: SCITEX convention (3129X scheme)
DEFAULT_PORT = int(os.environ.get("OPENALEX_LOCAL_PORT", "31292"))
DEFAULT_HOST = os.environ.get("OPENALEX_LOCAL_HOST", "0.0.0.0")


def run_server(host: str = None, port: int = None, force: bool = False):
    """Run the FastAPI server.

    Args:
        host: Host to bind to (default: 0.0.0.0)
        port: Port to listen on (default: 31292)
        force: If True, kill any existing process using the port
    """
    import uvicorn

    host = host or DEFAULT_HOST
    port = port or DEFAULT_PORT

    if force:
        from .._cli.utils import kill_process_on_port

        kill_process_on_port(port)

    uvicorn.run(app, host=host, port=port)


__all__ = ["app", "run_server", "DEFAULT_PORT", "DEFAULT_HOST"]
