"""FastAPI server for OpenAlex Local with FTS5 search.

Provides HTTP relay server for remote database access.

Usage:
    openalex-local relay                    # Run on default port 31292
    openalex-local relay --port 8080        # Custom port

    # Or directly:
    uvicorn openalex_local.server:app --host 0.0.0.0 --port 31292
"""

import os

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:  # fastapi absent — the [server]-gated HTTP capability only
    FastAPI = None  # type: ignore[assignment]
    CORSMiddleware = None  # type: ignore[assignment]

SERVER_AVAILABLE = FastAPI is not None
SERVER_EXTRA_HINT = "pip install 'openalex-local[server]'"

from .. import __version__

if SERVER_AVAILABLE:
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
else:
    app = None


def _register_routes() -> None:
    """Register plain route functions against the FastAPI app.

    A no-op without fastapi: there is no app to register against.
    """
    if app is None:
        return
    app.get("/")(root)
    app.get("/health")(health)
    app.get("/info")(info)


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


def health():
    """Health check endpoint."""
    from .._core.db import get_db

    try:
        db = get_db()
        return {
            "status": "healthy",
            "database_connected": db is not None,
            "database_path": str(db.db_path) if db else None,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


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
            "database_path": None,
        }

    # Use _metadata table for pre-computed counts (COUNT(*) on 459M rows is too slow)
    work_count = 0
    fts_count = 0
    try:
        row = db.fetchone("SELECT value FROM _metadata WHERE key = 'total_works'")
        if row:
            work_count = int(row["value"])
        row = db.fetchone("SELECT value FROM _metadata WHERE key = 'fts_total_indexed'")
        if row:
            fts_count = int(row["value"])
    except Exception:
        pass  # _metadata table may not exist in older databases

    return {
        "name": "OpenAlex Local API",
        "version": __version__,
        "status": "running",
        "mode": "local",
        "total_works": work_count,
        "fts_indexed": fts_count,
        "database_path": str(db.db_path),
    }


# Default port: SCITEX convention (3129X scheme)
DEFAULT_PORT = int(os.environ.get("OPENALEX_LOCAL_PORT", "31292"))
DEFAULT_HOST = os.environ.get("OPENALEX_LOCAL_HOST", "0.0.0.0")


_register_routes()


def run_server(host: str = None, port: int = None, force: bool = False):
    """Run the FastAPI server.

    Args:
        host: Host to bind to (default: 0.0.0.0)
        port: Port to listen on (default: 31292)
        force: If True, kill any existing process using the port
    """
    try:
        import uvicorn
    except ImportError as e:
        raise RuntimeError(
            "uvicorn is not installed, so the openalex-local HTTP server is "
            f"unavailable. Install it with: {SERVER_EXTRA_HINT}"
        ) from e

    if app is None:
        raise RuntimeError(
            "fastapi is not installed, so the openalex-local HTTP server is "
            f"unavailable. Install it with: {SERVER_EXTRA_HINT}"
        )

    host = host or DEFAULT_HOST
    port = port or DEFAULT_PORT

    if force:
        from .._cli.utils import kill_process_on_port

        kill_process_on_port(port)

    uvicorn.run(app, host=host, port=port)


__all__ = ["app", "run_server", "DEFAULT_PORT", "DEFAULT_HOST"]
