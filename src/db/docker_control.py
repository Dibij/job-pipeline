"""Docker and PostgreSQL lifecycle management.

Ensures Docker daemon is running (automatically launching Docker Desktop if needed)
and starts the PostgreSQL container via docker compose.
"""
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def is_postgres_healthy(timeout: float = 2.0) -> bool:
    """Quickly check if PostgreSQL is currently accepting connections."""
    try:
        from src.db.connection import check_db_health
        health = check_db_health()
        return health.get("status") == "healthy"
    except Exception:
        return False


def is_docker_daemon_responsive(timeout: float = 3.0) -> bool:
    """Check if the docker CLI can reach the docker daemon."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False
    try:
        res = subprocess.run(
            [docker_bin, "info"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return res.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def find_docker_desktop_executable() -> Optional[Path]:
    """Find the path to the Docker Desktop application executable."""
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe",
            Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe"),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Docker" / "Docker" / "Docker Desktop.exe",
        ]
        for p in candidates:
            if p.is_file():
                return p
        which = shutil.which("Docker Desktop") or shutil.which("docker-desktop")
        if which:
            return Path(which)
    elif sys.platform == "darwin":
        mac_path = Path("/Applications/Docker.app")
        if mac_path.exists():
            return mac_path
    return None


def launch_docker_desktop() -> bool:
    """Launch Docker Desktop in the background."""
    if sys.platform == "win32":
        exe = find_docker_desktop_executable()
        if not exe:
            logger.warning("Docker Desktop executable not found in standard paths.")
            return False

        logger.info("Opening Docker Desktop: %s", exe)
        try:
            # Set working directory to frontend if it exists (standard Electron layout)
            working_dir = exe.parent / "frontend"
            if not working_dir.exists():
                working_dir = exe.parent

            creation_flags = 0
            if hasattr(subprocess, "DETACHED_PROCESS"):
                creation_flags |= subprocess.DETACHED_PROCESS
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                creation_flags |= subprocess.CREATE_NEW_PROCESS_GROUP

            subprocess.Popen(
                [str(exe)],
                cwd=str(working_dir),
                close_fds=True,
                creationflags=creation_flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as exc:
            logger.warning("Failed to launch Docker Desktop via Popen: %s. Trying os.startfile...", exc)
            try:
                os.startfile(str(exe))
                return True
            except Exception as e2:
                logger.error("Failed to start Docker Desktop: %s", e2)
                return False

    elif sys.platform == "darwin":
        logger.info("Opening Docker Desktop on macOS...")
        try:
            subprocess.Popen(["open", "-a", "Docker"])
            return True
        except Exception as exc:
            logger.error("Failed to open Docker on macOS: %s", exc)
            return False

    elif sys.platform.startswith("linux"):
        logger.info("Starting Docker service on Linux...")
        try:
            subprocess.run(["systemctl", "start", "docker"], check=False)
            return True
        except Exception as exc:
            logger.error("Failed to start docker service on Linux: %s", exc)
            return False

    return False


def wait_for_docker_daemon(timeout_seconds: int = 90) -> bool:
    """Poll docker info until the daemon is responsive or timeout."""
    start = time.time()
    logger.info("Waiting for Docker daemon to become responsive (up to %ds)...", timeout_seconds)
    while time.time() - start < timeout_seconds:
        if is_docker_daemon_responsive(timeout=3.0):
            elapsed = time.time() - start
            logger.info("Docker daemon is ready (took %.1fs).", elapsed)
            return True
        time.sleep(2.0)
    logger.error("Timed out waiting for Docker daemon after %ds.", timeout_seconds)
    return False


def start_postgres_container() -> bool:
    """Run docker compose up -d postgres using the project docker-compose.yml."""
    compose_file = PROJECT_ROOT / "docker-compose.yml"
    if not compose_file.exists():
        logger.error("docker-compose.yml not found at %s", compose_file)
        return False

    docker_bin = shutil.which("docker")
    if not docker_bin:
        logger.error("'docker' binary not found on PATH.")
        return False

    logger.info("Starting PostgreSQL container via docker compose...")
    try:
        res = subprocess.run(
            [docker_bin, "compose", "-f", str(compose_file), "up", "-d", "postgres"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode == 0:
            logger.info("PostgreSQL container startup command succeeded.")
            return True
        else:
            logger.error("docker compose up failed: %s %s", res.stdout, res.stderr)
            return False
    except Exception as exc:
        logger.error("Error executing docker compose up: %s", exc)
        return False


def wait_for_postgres_healthy(timeout_seconds: int = 45) -> bool:
    """Poll PostgreSQL until it is healthy and accepting connections."""
    start = time.time()
    logger.info("Waiting for PostgreSQL to accept connections (up to %ds)...", timeout_seconds)
    while time.time() - start < timeout_seconds:
        if is_postgres_healthy(timeout=2.0):
            elapsed = time.time() - start
            logger.info("PostgreSQL is healthy and accepting queries (took %.1fs).", elapsed)
            return True
        time.sleep(1.5)
    logger.error("Timed out waiting for PostgreSQL health after %ds.", timeout_seconds)
    return False


def ensure_docker_and_postgres(
    daemon_timeout: int = 90,
    pg_timeout: int = 45,
) -> bool:
    """Ensure Docker Desktop is open and PostgreSQL is running and healthy.

    If PostgreSQL is already up, this returns in <50ms without touching Docker.
    If Docker is not running, it automatically opens Docker Desktop, waits for
    the daemon to initialize, brings up the postgres container, and waits for
    connection health.
    """
    # 1. Fast path: check if already running
    if is_postgres_healthy():
        logger.info("PostgreSQL is already running and healthy.")
        return True

    # 2. Check if Docker daemon is responsive
    if not is_docker_daemon_responsive():
        logger.warning("Docker daemon is not responding. Automatically opening Docker Desktop...")
        launched = launch_docker_desktop()
        if not launched:
            logger.warning("Could not automatically launch Docker Desktop. Will wait in case it is starting...")

        # Wait for daemon
        if not wait_for_docker_daemon(timeout_seconds=daemon_timeout):
            return False
    else:
        logger.info("Docker daemon is responsive.")

    # 3. Ensure postgres container is started
    if not start_postgres_container():
        return False

    # 4. Wait for postgres connection
    return wait_for_postgres_healthy(timeout_seconds=pg_timeout)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    success = ensure_docker_and_postgres()
    print("Success:", success)
