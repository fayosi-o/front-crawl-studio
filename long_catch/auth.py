"""Single-process, in-memory access control for the optional Render deployment."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import parse_qs

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from starlette.requests import HTTPConnection, Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SESSION_SECONDS = 12 * 60 * 60
COOKIE = '__Host-long-catch'
LOGIN_FORM = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Long Catch - Sign in</title><body>
<h1>Long Catch</h1><p>Sign in to your private stroke explorer.</p>
<form method="post" action="/login">
<p><label>Username <input name="username" autocomplete="username" required maxlength="256"></label></p>
<p><label>Password <input type="password" name="password" autocomplete="current-password"
required maxlength="1024"></label></p><button>Sign in</button></form></body></html>"""


def hosted(environ: Mapping[str, str] = os.environ) -> bool:
    return bool(environ.get('PORT') or environ.get('RENDER'))


@dataclass(frozen=True)
class AuthConfig:
    username: str
    password_hash: str = field(repr=False)
    secret: str = field(repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> AuthConfig | None:
        if not hosted(environ):
            return None
        names = ('APP_USERNAME', 'APP_PASSWORD_HASH', 'SESSION_SECRET')
        if any(not environ.get(name, '').strip() for name in names):
            raise RuntimeError('Hosted mode requires APP_USERNAME, APP_PASSWORD_HASH and SESSION_SECRET.')
        if len(environ['SESSION_SECRET']) < 32:
            raise RuntimeError('SESSION_SECRET must contain at least 32 characters.')
        try:
            params = extract_parameters(environ['APP_PASSWORD_HASH'])
        except InvalidHashError:
            raise RuntimeError('APP_PASSWORD_HASH must be a valid Argon2 hash.') from None
        if (
            params.type != Type.ID
            or params.memory_cost != 65536
            or params.time_cost != 3
            or params.parallelism != 4
            or params.hash_len < 32
            or params.salt_len < 16
        ):
            raise RuntimeError('Generate APP_PASSWORD_HASH using the documented password helper.')
        try:
            PasswordHasher().verify(environ['APP_PASSWORD_HASH'], secrets.token_urlsafe(32))
        except VerifyMismatchError:
            pass
        except VerificationError:
            raise RuntimeError('APP_PASSWORD_HASH must be a valid Argon2 hash.') from None
        return cls(*(environ[name] for name in names))


@dataclass
class Session:
    expires: float
    revoked: asyncio.Event = field(default_factory=asyncio.Event)


class PrivateAccess:
    """Gate HTTP, static assets and NiceGUI's Socket.IO transport before routing."""

    def __init__(self, app: ASGIApp, config: AuthConfig | None) -> None:
        self.app = app
        self.config = config
        self.sessions: dict[str, Session] = {}
        self.attempts: deque[tuple[float, str]] = deque()
        self.verifier = asyncio.Semaphore(1)

    def key(self, token: str) -> str:
        assert self.config is not None
        return hmac.new(self.config.secret.encode(), token.encode(), hashlib.sha256).hexdigest()

    def session(self, request: HTTPConnection) -> Session | None:
        for key, session in list(self.sessions.items()):
            if session.expires <= time.monotonic():
                session.revoked.set()
                del self.sessions[key]
        return self.sessions.get(self.key(request.cookies.get(COOKIE, '')))

    @staticmethod
    def same_origin(request: HTTPConnection) -> bool:
        return request.headers.get('origin') == f'https://{request.headers.get("host")}'

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] not in {'http', 'websocket'}:
            await self.app(scope, receive, send)
            return
        request = HTTPConnection(scope)
        path = scope['path']
        if scope['type'] == 'http' and path == '/health' and scope['method'] in {'GET', 'HEAD'}:
            await JSONResponse({'status': 'ok'})(scope, receive, send)
            return
        if self.config is None:
            await self.app(scope, receive, send)
            return

        async def secure_send(message: Message) -> None:
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                headers = [(k, v) for k, v in headers if k.lower() != b'cache-control']
                headers.extend(
                    [
                        (b'cache-control', b'no-store'),
                        (b'x-content-type-options', b'nosniff'),
                        (b'referrer-policy', b'same-origin'),
                        (b'x-frame-options', b'DENY'),
                    ]
                )
                message = {**message, 'headers': headers}
            await send(message)

        session = self.session(request)
        if scope['type'] == 'websocket':
            if session is None or not self.same_origin(request):
                await receive()
                await send({'type': 'websocket.close', 'code': 1008})
                return
            await self.websocket(scope, receive, send, session)
            return
        if path == '/login':
            response = await self.login(Request(scope, receive))
        elif session is None:
            response = (
                RedirectResponse('/login', status_code=303)
                if path == '/' or 'text/html' in request.headers.get('accept', '')
                else JSONResponse({'detail': 'Authentication required'}, status_code=401)
            )
        elif path == '/logout':
            if scope['method'] == 'POST' and self.same_origin(request):
                session.revoked.set()
                self.sessions.pop(self.key(request.cookies.get(COOKIE, '')), None)
                response = RedirectResponse('/login', status_code=303)
                response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='lax')
            elif scope['method'] == 'GET':
                response = HTMLResponse(
                    '<!doctype html><title>Long Catch - Sign out</title>'
                    '<form method="post" action="/logout"><button>Sign out</button></form>'
                )
            else:
                response = Response(status_code=403)
        elif (
            scope['method'] not in {'GET', 'HEAD', 'OPTIONS'} or request.headers.get('origin')
        ) and not self.same_origin(request):
            response = Response(status_code=403)
        else:
            await self.app(scope, receive, secure_send)
            return
        await response(scope, receive, secure_send)

    async def login(self, request: Request) -> Response:
        if request.method == 'GET':
            return HTMLResponse(LOGIN_FORM)
        if request.method != 'POST' or not self.same_origin(request):
            return Response(status_code=403)
        now = time.monotonic()
        while self.attempts and self.attempts[0][0] <= now - 60:
            self.attempts.popleft()
        ip = request.client.host if request.client else ''
        if len(self.attempts) >= 20 or sum(address == ip for _, address in self.attempts) >= 5:
            return HTMLResponse('Too many attempts. Try again in a minute.', 429, headers={'Retry-After': '60'})
        self.attempts.append((now, ip))
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                return Response(status_code=413)
        try:
            fields = parse_qs(body.decode('utf-8', errors='replace'), max_num_fields=10)
        except ValueError:
            return Response('Invalid login form', status_code=400)
        username = fields.get('username', [''])[0]
        password = fields.get('password', [''])[0]
        assert self.config is not None
        valid = False
        if len(username) <= 256 and len(password) <= 1024:
            async with self.verifier:
                try:
                    valid = await asyncio.to_thread(PasswordHasher().verify, self.config.password_hash, password)
                except VerificationError:
                    valid = False
            valid = hmac.compare_digest(username.encode(), self.config.username.encode()) and valid
        if not valid:
            return HTMLResponse('<p>Invalid username or password.</p><a href="/login">Try again</a>', 401)
        old = self.sessions.pop(self.key(request.cookies.get(COOKIE, '')), None)
        if old is not None:
            old.revoked.set()
        if len(self.sessions) >= 32:
            self.sessions.pop(next(iter(self.sessions))).revoked.set()
        token = secrets.token_urlsafe(32)
        self.sessions[self.key(token)] = Session(time.monotonic() + SESSION_SECONDS)
        response = RedirectResponse('/', status_code=303)
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, secure=True, httponly=True, samesite='lax')
        return response

    async def websocket(self, scope: Scope, receive: Receive, send: Send, session: Session) -> None:
        closed = False

        async def track_send(message: Message) -> None:
            nonlocal closed
            if message['type'] == 'websocket.close':
                closed = True
            await send(message)

        transport = asyncio.create_task(self.app(scope, receive, track_send))
        revoked = asyncio.create_task(session.revoked.wait())
        try:
            await asyncio.wait(
                (transport, revoked),
                timeout=max(0, session.expires - time.monotonic()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if transport.done():
                await transport
            elif not closed:
                await send({'type': 'websocket.close', 'code': 1008})
        finally:
            transport.cancel()
            revoked.cancel()
            await asyncio.gather(transport, revoked, return_exceptions=True)
