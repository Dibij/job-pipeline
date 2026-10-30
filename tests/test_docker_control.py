"""Unit tests for Docker and PostgreSQL lifecycle control (src/db/docker_control.py)."""
from unittest.mock import patch, MagicMock
from src.db.docker_control import (
    is_postgres_healthy,
    is_docker_daemon_responsive,
    find_docker_desktop_executable,
    ensure_docker_and_postgres,
)


def test_is_postgres_healthy_returns_bool():
    result = is_postgres_healthy(timeout=1.0)
    assert isinstance(result, bool)


def test_is_docker_daemon_responsive_returns_bool():
    result = is_docker_daemon_responsive(timeout=1.0)
    assert isinstance(result, bool)


def test_find_docker_desktop_executable_smoke():
    exe = find_docker_desktop_executable()
    # On Windows if Docker Desktop is installed, it returns a Path
    if exe is not None:
        assert str(exe).endswith("Docker Desktop.exe") or "Docker" in str(exe)


def test_ensure_docker_and_postgres_fast_path():
    with patch("src.db.docker_control.is_postgres_healthy", return_value=True):
        with patch("src.db.docker_control.launch_docker_desktop") as mock_launch:
            success = ensure_docker_and_postgres()
            assert success is True
            mock_launch.assert_not_called()


def test_ensure_docker_and_postgres_launches_docker_when_down():
    with patch("src.db.docker_control.is_postgres_healthy", side_effect=[False, True]), \
         patch("src.db.docker_control.is_docker_daemon_responsive", return_value=False), \
         patch("src.db.docker_control.launch_docker_desktop", return_value=True) as mock_launch, \
         patch("src.db.docker_control.wait_for_docker_daemon", return_value=True), \
         patch("src.db.docker_control.start_postgres_container", return_value=True) as mock_start_pg, \
         patch("src.db.docker_control.wait_for_postgres_healthy", return_value=True):

        success = ensure_docker_and_postgres()
        assert success is True
        mock_launch.assert_called_once()
        mock_start_pg.assert_called_once()


def test_ensure_docker_and_postgres_fails_if_daemon_timeout():
    with patch("src.db.docker_control.is_postgres_healthy", return_value=False), \
         patch("src.db.docker_control.is_docker_daemon_responsive", return_value=False), \
         patch("src.db.docker_control.launch_docker_desktop", return_value=True), \
         patch("src.db.docker_control.wait_for_docker_daemon", return_value=False):

        success = ensure_docker_and_postgres(daemon_timeout=1)
        assert success is False
