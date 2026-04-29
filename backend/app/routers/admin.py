"""Admin-only endpoints: service control.

Currently exposes a single action — ``POST /admin/restart`` — that kicks
off a full restart of Redis (if stopped), the backend, the Celery worker,
and the frontend dev server.

Mechanism
---------
A Python process on Windows cannot safely kill and respawn itself inline
— the parent dies the moment you kill it, and any Popen it spawned would
go with it unless explicitly detached. We sidestep that with a *trampoline*:

    1. The HTTP handler returns 202 immediately.
    2. A background thread spawns ``scripts/restart_services.ps1`` as a
       fully detached process (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP).
    3. That PowerShell script sleeps briefly (``-Delay 2``), then kills
       every service (including this backend) and relaunches them.

So from the client's perspective: the 202 flies, then the server goes
quiet for ~5-10s, then the new backend is up on the same port.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

# Repo root is three parents up from this file: routers -> app -> backend -> repo
REPO_ROOT = Path(__file__).resolve().parents[3]
RESTART_SCRIPT = REPO_ROOT / "scripts" / "restart_services.ps1"

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_user)],
)


def _spawn_restart_trampoline(skip_frontend: bool, delay: int) -> None:
    """Spawn the PowerShell restart script as a detached process.

    Runs in a background daemon thread so the HTTP handler is free to
    return its 202 before the trampoline actually fires the kill.
    """
    # Tiny in-thread delay to let the HTTP response flush.
    time.sleep(0.5)

    args: list[str] = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(RESTART_SCRIPT),
        "-Delay", str(delay),
    ]
    if skip_frontend:
        args.append("-SkipFrontend")

    # Detach so the trampoline outlives this process. NOTE: we use
    # CREATE_NEW_CONSOLE rather than DETACHED_PROCESS — the latter
    # combined with close_fds=True causes PowerShell to exit immediately
    # without running the script on Windows 10/11. The new-console child
    # is hidden in our scheduled-task infra and visible in raw CLI use;
    # both are fine.
    if sys.platform == "win32":
        creationflags = (
            subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
            | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        creationflags = 0

    try:
        # Don't pass DEVNULL for stdin/stdout/stderr here — with
        # CREATE_NEW_CONSOLE the child gets its own console, and forcing
        # close_fds + DEVNULL seems to cause PowerShell to exit before
        # running the script on some Windows builds. Leaving the streams
        # inherited + close_fds=True works reliably.
        subprocess.Popen(
            args,
            cwd=str(REPO_ROOT),
            creationflags=creationflags,
            close_fds=True,
        )
        logger.info("Spawned restart trampoline (skip_frontend=%s, delay=%ss)",
                    skip_frontend, delay)
    except Exception:
        logger.exception("Failed to spawn restart trampoline")


@router.post("/restart", status_code=status.HTTP_202_ACCEPTED)
def restart_services(skip_frontend: bool = False, delay: int = 2) -> dict:
    """Restart every runtime that makes up Pratidhvani.

    Returns 202 immediately; the actual restart happens out-of-band via a
    detached PowerShell script that kills this process and relaunches it
    alongside Celery, Redis (if stopped), and optionally the frontend.

    Query parameters
    ----------------
    skip_frontend : bool, default False
        If true, leave the Vite dev server alone. Useful when you only
        changed backend code.
    delay : int, default 2
        Seconds the trampoline waits before beginning the kill phase.
        The default gives the client enough time to receive the 202.

    Authentication
    --------------
    Requires a valid bearer token (standard app auth).
    """
    if not RESTART_SCRIPT.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Restart script missing at {RESTART_SCRIPT}",
        )

    if sys.platform != "win32":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Self-restart is only wired up for Windows hosts today.",
        )

    thread = threading.Thread(
        target=_spawn_restart_trampoline,
        args=(skip_frontend, delay),
        daemon=True,
    )
    thread.start()

    return {
        "status": "accepted",
        "message": (
            f"Restart scheduled in ~{delay}s. This process will be killed "
            "and replaced; the backend should be reachable again within "
            "~5-10 seconds."
        ),
        "skip_frontend": skip_frontend,
    }
