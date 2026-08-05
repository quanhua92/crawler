"""Auth routes — browser login form + cookie issuance."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import sign_session, try_auth
from app.config import settings

router = APIRouter()

_AUTH_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>crawler — sign in</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center;
         font:16px/1.5 system-ui,-apple-system,sans-serif; background:#0b0b0d; color:#e7e7ea; }}
  .card {{ width:min(92vw,380px); padding:2rem; border-radius:14px; background:#17171a;
          border:1px solid #2a2a30; }}
  h1 {{ font-size:1.2rem; margin:0 0 1.5rem; }}
  input {{ width:100%; padding:.7rem .9rem; margin-bottom 1rem; border-radius:8px;
           border:1px solid #2a2a30; background:#0b0b0d; color:#e7e7ea; font-size:1rem; }}
  button {{ width:100%; padding:.7rem; border:none; border-radius:8px; background:#3b82f6;
            color:#fff; font-size:1rem; cursor:pointer; }}
  button:hover {{ background:#2563eb; }}
  .error {{ color:#f87171; margin-top:.5rem; font-size:.9rem; }}
  .hint {{ margin-top:1rem; font-size:.8rem; opacity:.6; }}
</style></head><body>
<main class="card">
  <h1>🐛 crawler</h1>
  <form method="POST" action="/auth">
    <input type="password" name="key" placeholder="API key" autofocus required>
    <button type="submit">Sign in</button>
    {error}
  </form>
  <p class="hint">Or use <code>Authorization: Bearer &lt;key&gt;</code> for API access.</p>
</main></body></html>
"""

_LANDING_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>crawler</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center;
         font:16px/1.5 system-ui,sans-serif; background:#0b0b0d; color:#e7e7ea; }}
  .card {{ padding:2rem; border-radius:14px; background:#17171a; border:1px solid #2a2a30; }}
  h1 {{ font-size:1.2rem; }}
  a {{ color:#3b82f6; }}
  code {{ background:#2a2a30; padding:2px 6px; border-radius:4px; }}
</style></head><body>
<main class="card">
  <h1>✓ Authenticated</h1>
  <p>Try: <a href="/x/QwenDevs?limit=3"><code>/x/QwenDevs?limit=3</code></a></p>
  <p>Or: <a href="/substack/lennysnewsletter?limit=3"><code>/substack/...</code></a></p>
  <p>Full API docs: <a href="/docs">/docs</a></p>
</main></body></html>
"""


@router.get("/auth", response_class=HTMLResponse)
async def auth_form(request: Request):
    """Browser login form. Redirects to / if already authed."""
    if try_auth(request):
        return RedirectResponse("/", status_code=302)
    return HTMLResponse(_AUTH_HTML.format(error=""))


@router.post("/auth")
async def auth_login(key: str = Form(...)):
    """Validate key, set signed cookie, redirect to landing."""
    if key.strip() not in settings.api_keys_set:
        return HTMLResponse(
            _AUTH_HTML.format(error='<p class="error">Invalid key</p>'),
            status_code=401,
        )
    token = sign_session(key.strip())
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl,
        httponly=True,
        secure=False,  # set True behind HTTPS reverse proxy
        samesite="lax",
    )
    return resp


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    """Simple landing page for browser users."""
    if not try_auth(request):
        return RedirectResponse("/auth", status_code=302)
    return HTMLResponse(_LANDING_HTML)
