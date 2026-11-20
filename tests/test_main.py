import os
import socket
import subprocess
import sys

from main import LOCAL_PORTS, free_port, server_address


def test_server_address_stays_local_on_a_free_port_without_port():
    host, port = server_address({})
    assert host == '127.0.0.1'
    assert port in LOCAL_PORTS


def test_free_port_skips_a_port_in_use():
    with socket.socket() as taken:
        taken.bind(('127.0.0.1', 0))
        taken.listen()
        busy = taken.getsockname()[1]
        assert all(free_port() != busy for _ in range(50))


def test_server_address_can_be_pinned_locally():
    assert server_address({'LONG_CATCH_PORT': '8080'}) == ('127.0.0.1', 8080)


def test_server_address_uses_render_port():
    assert server_address({'PORT': '10000'}) == ('0.0.0.0', 10000)


def test_hosted_startup_without_credentials_exits_safely():
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {'APP_USERNAME', 'APP_PASSWORD_HASH', 'SESSION_SECRET'}
    }
    result = subprocess.run(
        [sys.executable, 'main.py'],
        env={**env, 'PORT': '10000'},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert 'Hosted mode requires APP_USERNAME, APP_PASSWORD_HASH and SESSION_SECRET.' in result.stderr
