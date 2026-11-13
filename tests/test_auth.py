import secrets
import time

import pytest
from argon2 import PasswordHasher
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from long_catch.auth import COOKIE, SESSION_SECONDS, AuthConfig, PrivateAccess


@pytest.fixture(scope='module')
def credentials():
    password = secrets.token_urlsafe(24)
    config = AuthConfig('tester', PasswordHasher().hash(password), secrets.token_urlsafe(48))
    return config, password


@pytest.fixture
def access(credentials):
    async def endpoint(request):
        return JSONResponse({'protected': True})

    async def socket(websocket):
        await websocket.accept()
        while True:
            await websocket.send_text(await websocket.receive_text())

    routes = [Route('/{path:path}', endpoint, methods=['GET', 'POST']), WebSocketRoute('/ws', socket)]
    return PrivateAccess(Starlette(routes=routes), credentials[0])


@pytest.fixture
def client(access):
    with TestClient(access, base_url='https://testserver', headers={'origin': 'https://testserver'}) as client:
        yield client


def login(client, credentials, **overrides):
    return client.post(
        '/login',
        data={'username': credentials[0].username, 'password': credentials[1], **overrides},
        follow_redirects=False,
    )


def test_hosted_configuration_fails_closed(credentials):
    config, _ = credentials
    env = {
        'PORT': '10000',
        'APP_USERNAME': config.username,
        'APP_PASSWORD_HASH': config.password_hash,
        'SESSION_SECRET': config.secret,
    }
    assert AuthConfig.from_env(env) == config
    assert AuthConfig.from_env({}) is None
    for mode in ({'PORT': '10000'}, {'RENDER': 'true'}):
        with pytest.raises(RuntimeError, match='requires'):
            AuthConfig.from_env(mode)
    for key in ('APP_USERNAME', 'APP_PASSWORD_HASH', 'SESSION_SECRET'):
        with pytest.raises(RuntimeError):
            AuthConfig.from_env({**env, key: ''})
    for value in ('plaintext', '$argon2id$invalid'):
        with pytest.raises(RuntimeError, match='Argon2'):
            AuthConfig.from_env({**env, 'APP_PASSWORD_HASH': value})
    with pytest.raises(RuntimeError, match='32 characters'):
        AuthConfig.from_env({**env, 'SESSION_SECRET': 'short'})


def test_local_access_and_health_stay_public(access):
    access.config = None
    with TestClient(access) as client:
        assert client.get('/').json() == {'protected': True}
        assert client.get('/health').json() == {'status': 'ok'}


def test_unauthenticated_routes_and_websocket_are_gated(client):
    response = client.get('/', follow_redirects=False)
    assert response.status_code == 303
    assert response.headers['location'] == '/login'
    for path in (
        '/api/test',
        '/results/test',
        '/exports/test',
        '/download/test',
        '/_nicegui/test/static/file.js',
        '/_nicegui_ws/socket.io/?EIO=4&transport=polling',
        '/logout',
    ):
        assert client.get(path).status_code == 401
    assert client.get('/health').json() == {'status': 'ok'}
    assert client.get('/login').status_code == 200
    with pytest.raises(WebSocketDisconnect) as error, client.websocket_connect('wss://testserver/ws'):
        pass
    assert error.value.code == 1008


def test_login_logout_rotation_and_cookie_security(client, credentials, access):
    response = login(client, credentials)
    assert response.status_code == 303
    cookie = response.headers['set-cookie']
    for flag in ('Secure', 'HttpOnly', 'SameSite=lax', f'Max-Age={SESSION_SECONDS}', 'Path=/'):
        assert flag in cookie
    assert response.headers['cache-control'] == 'no-store'
    original = client.cookies.get(COOKIE)
    assert client.get('/').json() == {'protected': True}
    login(client, credentials)
    assert client.cookies.get(COOKIE) != original
    assert access.key(original) not in access.sessions
    current = client.cookies.get(COOKIE)
    assert client.get('/logout').status_code == 200
    assert client.get('/').status_code == 200
    assert client.post('/logout', follow_redirects=False).status_code == 303
    client.cookies.set(COOKIE, current)
    assert client.get('/api/test').status_code == 401


def test_invalid_login_rate_limit_and_origin_checks(client, credentials):
    wrong_user = login(client, credentials, username='unknown')
    wrong_password = login(client, credentials, password=secrets.token_urlsafe(24))
    assert wrong_user.status_code == wrong_password.status_code == 401
    assert wrong_user.text == wrong_password.text
    for _ in range(3):
        login(client, credentials, password='')
    assert login(client, credentials).status_code == 429
    assert client.get('/health').status_code == 200
    assert client.post('/login', headers={'origin': 'https://evil.example'}).status_code == 403


def test_session_expiry_and_cross_origin_socket(client, credentials, access):
    login(client, credentials)
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect('wss://testserver/ws', headers={'origin': 'https://evil.example'}),
    ):
        pass
    session = next(iter(access.sessions.values()))
    session.expires = time.monotonic() - 1
    assert client.get('/api/test').status_code == 401
    assert session.revoked.is_set()


def test_forged_cookie_and_expiry_of_open_socket(client, credentials, access):
    client.cookies.set(COOKIE, secrets.token_urlsafe(32))
    assert client.get('/api/test').status_code == 401
    client.cookies.clear()
    login(client, credentials)
    next(iter(access.sessions.values())).expires = time.monotonic() + 0.1
    with client.websocket_connect('wss://testserver/ws') as socket:
        with pytest.raises(WebSocketDisconnect) as error:
            socket.receive_text()
        assert error.value.code == 1008


def test_live_socket_is_revoked_on_logout(client, credentials):
    login(client, credentials)
    with client.websocket_connect('wss://testserver/ws') as socket:
        socket.send_text('connected')
        assert socket.receive_text() == 'connected'
        assert client.post('/logout', follow_redirects=False).status_code == 303
        with pytest.raises(WebSocketDisconnect) as error:
            socket.receive_text()
        assert error.value.code == 1008


def test_login_payload_limits_and_csrf(client, credentials):
    assert client.post('/login', content=b'x' * 8193).status_code == 413
    assert client.post('/login', content='&'.join(f'x{i}=x' for i in range(11))).status_code == 400
    login(client, credentials)
    assert client.post('/logout', headers={'origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/test', headers={'origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/test').status_code == 200
