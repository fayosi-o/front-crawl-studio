import asyncio
import secrets
import time

import pytest
from argon2 import PasswordHasher
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from long_catch import auth
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


def test_rate_limit_keys_on_the_client_cloudflare_names(client, credentials):
    # On Render, Cloudflare names the client in CF-Connecting-IP (and refuses requests that set it
    # themselves); X-Forwarded-For starts with whatever the client sent and ends with Render's proxies.
    def attempt(cloudflare, forwarded):
        return client.post(
            '/login',
            data={'username': 'x', 'password': ''},
            headers={'cf-connecting-ip': cloudflare, 'x-forwarded-for': f'{forwarded}, 104.23.0.1, 10.28.0.1'},
        )

    for i in range(5):
        assert attempt('203.0.113.7', f'198.51.100.{i}').status_code == 401
    # A different forged X-Forwarded-For does not give the same client fresh guesses.
    assert attempt('203.0.113.7', '198.51.100.99').status_code == 429
    # Someone else behind the same Render proxies can still sign in.
    other = client.post(
        '/login',
        data={'username': credentials[0].username, 'password': credentials[1]},
        headers={'cf-connecting-ip': '203.0.113.99', 'x-forwarded-for': '203.0.113.99, 104.23.0.1, 10.28.0.1'},
        follow_redirects=False,
    )
    assert other.status_code == 303


def test_global_backstop_caps_logins_whatever_the_header_says(client, credentials):
    for i in range(20):
        client.post('/login', data={'username': 'x', 'password': ''}, headers={'cf-connecting-ip': f'192.0.2.{i}'})
    assert client.post('/login', data={}, headers={'cf-connecting-ip': '192.0.2.200'}).status_code == 429
    assert client.get('/health').status_code == 200


def test_cross_site_requests_are_refused_but_links_to_the_app_work(client):
    navigate = {'sec-fetch-site': 'cross-site', 'sec-fetch-mode': 'navigate'}
    assert client.get('/', headers=navigate, follow_redirects=False).status_code == 303
    assert client.get('/', headers={**navigate, 'sec-fetch-mode': 'cors'}).status_code == 403
    assert client.post('/login', data={}, headers=navigate).status_code == 403


def test_oversized_login_is_refused_from_its_declared_length(client):
    response = client.post('/login', content=b'username=x', headers={'content-length': '100000'})
    assert response.status_code == 413


def raw_login(access, then, headers=(), hold_verifier=False):
    """POST /login straight to the middleware: a short form arrives, then the client finishes (``'end'``),
    stalls (``'stall'``) or hangs up (``'disconnect'``). Returns the status and the response headers."""
    scope = {
        'type': 'http',
        'http_version': '1.1',
        'method': 'POST',
        'scheme': 'https',
        'path': '/login',
        'raw_path': b'/login',
        'query_string': b'',
        'root_path': '',
        'server': ('testserver', 443),
        'client': ('203.0.113.5', 50000),
        'headers': [(b'host', b'testserver'), (b'origin', b'https://testserver'), *headers],
    }
    chunks = [{'type': 'http.request', 'body': b'username=x&password=y', 'more_body': then != 'end'}]
    sent = []

    async def receive():
        if chunks:
            return chunks.pop(0)
        if then == 'disconnect':
            return {'type': 'http.disconnect'}
        await asyncio.Event().wait()  # the rest of the body never comes

    async def send(message):
        sent.append(message)

    async def run():
        if hold_verifier:
            await access.verifier.acquire()  # someone else's password check is running
        try:
            await access(scope, receive, send)
        finally:
            if hold_verifier:
                access.verifier.release()

    asyncio.run(run())
    return sent[0]['status'], dict(sent[0]['headers'])


def test_login_reads_and_waits_are_bounded(access, monkeypatch):
    monkeypatch.setattr(auth, 'BODY_SECONDS', 0.05)
    monkeypatch.setattr(auth, 'VERIFY_WAIT_SECONDS', 0.05)
    assert raw_login(access, 'end', headers=[(b'content-length', b'12x')])[0] == 400
    assert raw_login(access, 'stall')[0] == 408
    assert raw_login(access, 'disconnect')[0] == 400
    status, headers = raw_login(access, 'end', hold_verifier=True)
    assert status == 503 and headers[b'retry-after'] == b'5'
    # A finished check gives the slot back.
    assert raw_login(access, 'end')[0] == 401
    assert not access.verifier.locked()
