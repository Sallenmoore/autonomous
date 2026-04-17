# Auth — AutoAuth and OAuth2

``AutoAuth`` ships the OAuth2 authorization-code flow, token exchange,
and the per-request "am I logged in?" decorator. It depends on
``Authlib`` but **not** on any web framework — you wire it to whatever
session your host framework provides.

## Concepts

- ``AutoAuth`` — base class. Subclass for a concrete provider.
- ``GoogleAuth`` / ``GithubAuth`` — provider-specific concrete
  subclasses in ``autonomous.auth.google`` / ``autonomous.auth.github``.
- ``AutoUser`` — default user model (``autonomous.auth.user.AutoUser``);
  stores email, name, role (``guest`` / ``user`` / ``admin``).
- ``@AutoAuth.auth_required()`` — view decorator.
- ``AutoAuth.current_user()`` — current user or ``None``.

Session state is held in whatever dict-like object you've bound via
``autonomous.web.bind_session``. That can be Flask's ``session``,
Starlette's ``request.session``, or a custom store.

## Minimal Flask wiring

```python
from flask import Flask, session as flask_session, redirect, request
from autonomous.auth.google import GoogleAuth
from autonomous.auth import AutoAuth
from autonomous.web import bind_session

app = Flask(__name__)
AutoAuth.login_url = "/auth/login"   # where @auth_required redirects

@app.before_request
def _bind():
    bind_session(flask_session)

auth = GoogleAuth(
    client_id="...",
    client_secret="...",
    redirect_uri="https://example.com/auth/callback",
)

@app.route("/auth/login")
def login():
    url, state = auth.authenticate()       # stores state in session
    return redirect(url)

@app.route("/auth/callback")
def callback():
    user = auth.handle_response(request.url)
    return redirect("/")

@app.route("/me")
@AutoAuth.auth_required()
def me():
    return AutoAuth.current_user().to_json()
```

## OAuth state — what ``handle_response`` checks

``AutoAuth.authenticate()`` mints a fresh nonce, stores it in the
session under ``state_session_key`` (default ``"oauth_state"``), and
embeds it in the outgoing URL.

``handle_response()`` reads the nonce back and refuses callbacks whose
``state`` parameter doesn't match. If no session binding is in place,
it raises ``MismatchingStateError`` so you can't accidentally ship a
CSRF-vulnerable deployment.

To coexist with multiple providers in one app, subclass and override
``state_session_key``:

```python
class GithubAuthForAdmin(GithubAuth):
    state_session_key = "oauth_state_github_admin"
```

## Login throttling

``auth_required`` used to write ``user.last_login`` and
``session["user"]`` on every request. That's at most one Mongo write
and one session write per pageview. Now it's throttled:

```python
AutoAuth.last_login_throttle_seconds = 60   # default
AutoAuth.last_login_throttle_seconds = 0    # opt out, save every call
```

``user.save()`` only fires when the last-login clock has advanced past
the threshold. ``session["user"] = user.to_json()`` only fires when
the rendered JSON changes.

## Guard view / admin view

```python
@AutoAuth.auth_required()                   # any authenticated user
def account(): ...

@AutoAuth.auth_required(roles=("admin",))   # role-gated
def admin_panel(): ...
```

Callers with no session return a redirect to ``AutoAuth.login_url``.
Callers with the wrong role get a 403 ``Response``. Both are
WSGI-callable, so they drop into any host framework unchanged.

## Custom providers

Subclass ``AutoAuth`` and implement:

- ``authenticate(**kwargs)`` — return ``(redirect_url, state)``.
- ``handle_response(url)`` — exchange the code, build the user.

See ``autonomous.auth.google.GoogleAuth`` for a full worked example
(~40 LOC). The parent class owns state management and user merging.

## FastAPI / pure WSGI

The library doesn't import ``flask``. Anywhere you have a dict-like
session + a URL, you have enough to run it:

```python
from autonomous.web import ContextSession, bind_session

def middleware(environ, start_response):
    bind_session(ContextSession())        # per-request dict session
    response = dispatch(environ)
    return response(environ, start_response)
```
