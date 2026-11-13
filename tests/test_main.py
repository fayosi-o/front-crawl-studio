import os
import subprocess
import sys

from main import server_address


def test_server_address_stays_local_without_port():
    assert server_address({}) == ('127.0.0.1', 8080)


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
