"""Google hesabıyla giriş (PROTOKOL.md §1).

Viewer "Desktop app" türündeki OAuth istemcisiyle giriyor: tarayıcı açılıyor,
kullanıcı hesabını seçip onaylıyor, Google kodu `http://127.0.0.1:<port>`'a
(bu süreçte kısa süre açılan bir dinleyiciye) gönderiyor, kod PKCE ile token'a
çevriliyor. Araç ve telefon AYNI Cloud projesinin kendi istemcileriyle giriyor;
`drive.file` kuralı gereği aynı projedeki istemciler birbirinin dosyasını
görüyor (2026-09-29'da gerçek Drive'a karşı doğrulandı).

İzin yalnızca `drive.file` (+ hangi hesap olduğunu göstermek için
`openid email`). Google'ın onay ekranı her izne ayrı kutu koyuyor ve Drive
kutusu boş bırakılabiliyor: giriş başarılı görünür ama her Drive çağrısı 403
döner. Bu yüzden token yanıtındaki `scope` her seferinde denetleniyor.

İstemci kimliği ve sırrı depoya girmiyor. Derleme sırasında `oauth.properties`
dosyasından `_oauth.py`'ye yazılıyor (`araclar/oauth-gom.py`); kaynaktan
çalışırken dosya doğrudan okunuyor. Google masaüstü uygulamalarında bu
değerleri gizli saymıyor — tek başlarına hiçbir veriye erişim vermiyorlar.
Erişim, kullanıcının bu bilgisayarda DPAPI ile şifrelenmiş refresh token'ında.
"""

from __future__ import annotations

import base64
import hashlib
import html
import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import i18n
from .drive import AccountCache, AuthError, DriveError, config_dir, http_request

SCOPE_DRIVE = "https://www.googleapis.com/auth/drive.file"
SCOPES = f"{SCOPE_DRIVE} openid email"

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

#: Tarayıcıdan onayın beklendiği en uzun süre.
SIGN_IN_TIMEOUT_S = 300

#: Access token'ın süresi dolmadan bu kadar önce yenileniyor: istek yoldayken
#: ölmesin.
EXPIRY_MARGIN_S = 60

#: (adres, form alanları) → (HTTP kodu, JSON gövde). Testte sahtesi.
Post = Callable[[str, dict[str, str]], tuple[int, dict]]


def post_form(url: str, data: dict[str, str]) -> tuple[int, dict]:
    status, raw = http_request(
        "POST",
        url,
        {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "EX30TripViewer"},
        urllib.parse.urlencode(data).encode("ascii"),
    )
    try:
        body = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        body = {}
    return status, body if isinstance(body, dict) else {}


# --- İstemci -----------------------------------------------------------------------


@dataclass(frozen=True)
class Client:
    id: str
    secret: str


def _properties_candidates() -> list[Path]:
    """Kaynaktan çalışırken `oauth.properties`'in aranacağı yerler."""
    here = Path(__file__).resolve().parent.parent
    paths = []
    if os.environ.get("EX30_OAUTH_PROPERTIES"):
        paths.append(Path(os.environ["EX30_OAUTH_PROPERTIES"]))
    paths.append(here / "oauth.properties")
    paths.append(here.parent / "EX30 Telemetry" / "oauth.properties")
    return paths


def read_properties(path: Path) -> Client | None:
    """`desktopClientId` / `desktopClientSecret` satırları; eksikse None."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    props: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            props[key.strip()] = value.strip()
    if props.get("desktopClientId") and props.get("desktopClientSecret"):
        return Client(props["desktopClientId"], props["desktopClientSecret"])
    return None


def load_client() -> Client:
    """Masaüstü OAuth istemcisi: önce derlemeye gömülen, yoksa dosyadan."""
    try:
        from . import _oauth  # type: ignore[attr-defined]
    except ImportError:
        _oauth = None
    if _oauth is not None and getattr(_oauth, "CLIENT_ID", "") and getattr(_oauth, "CLIENT_SECRET", ""):
        return Client(_oauth.CLIENT_ID, _oauth.CLIENT_SECRET)
    for path in _properties_candidates():
        client = read_properties(path)
        if client is not None:
            return client
    raise DriveError("auth.err.no_client")


# --- DPAPI ----------------------------------------------------------------------

#: DPAPI'ye verilen ek entropi: aynı Windows kullanıcısının başka bir
#: programı `CryptUnprotectData`'yı bu değeri bilmeden çağıramasın.
_ENTROPY = b"EX30TripViewer/refresh-token/1"


def _dpapi(data: bytes, protect: bool) -> bytes:
    """`CryptProtectData` / `CryptUnprotectData` — ctypes ile, bağımlılıksız.

    Şifre Windows oturumuna bağlı: aynı kullanıcı bu bilgisayarda çözebiliyor,
    dosyayı başka bilgisayara ya da kullanıcıya kopyalamak işe yaramıyor.
    """
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob_of(raw: bytes) -> tuple[Blob, object]:
        buffer = ctypes.create_string_buffer(raw, len(raw))
        return Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    data_in, keep_in = blob_of(data)
    entropy, keep_entropy = blob_of(_ENTROPY)
    data_out = Blob()
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(data_in), "EX30TripViewer", ctypes.byref(entropy),
            None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(data_in), None, ctypes.byref(entropy),
            None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out),
        )
    del keep_in, keep_entropy
    if not ok:
        raise OSError(ctypes.get_last_error(), "DPAPI")
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(data_out.pbData, ctypes.c_void_p))


def protect(secret: str) -> tuple[str, str]:
    """(koruma türü, base64 metin). Windows dışında DPAPI yok; orada token
    düz saklanıyor ve dosyada bu açıkça yazıyor."""
    raw = secret.encode("utf-8")
    if sys.platform == "win32":
        return "dpapi", base64.b64encode(_dpapi(raw, protect=True)).decode("ascii")
    return "yok", base64.b64encode(raw).decode("ascii")


def unprotect(kind: str, text: str) -> str:
    raw = base64.b64decode(text)
    if kind == "dpapi":
        raw = _dpapi(raw, protect=False)
    elif kind != "yok":
        raise ValueError(kind)
    return raw.decode("utf-8")


# --- Oturum ----------------------------------------------------------------------


def account_path() -> Path:
    """Bağlı hesap: e-posta + şifreli refresh token. Tek hesap: çıkış
    yapmadan ikinci biri bağlanamıyor, ama önbellekler hesap başına ayrı."""
    return config_dir() / "hesap.json"


def email_of(tokens: dict) -> str:
    """`id_token` gövdesindeki e-posta. İmza denetlenmiyor: token'ı Google'ın
    token ucundan TLS üstünden kendimiz aldık, araya giren yok."""
    try:
        payload = tokens["id_token"].split(".")[1]
        payload += "=" * (-len(payload) % 4)
        email = json.loads(base64.urlsafe_b64decode(payload)).get("email")
    except (KeyError, IndexError, ValueError, AttributeError, TypeError):
        return ""
    return email if isinstance(email, str) else ""


def require_drive(tokens: dict) -> None:
    """İzin kutusu tuzağı (§1): `scope`'ta `drive.file` yoksa bağlantı yok."""
    granted = str(tokens.get("scope") or "").split()
    if SCOPE_DRIVE not in granted:
        raise AuthError("auth.err.no_drive")


class Session:
    """Bağlı bir Google hesabı. `drive.TokenSource`'u karşılıyor.

    Access token yalnızca bellekte; diskte refresh token var. Birden çok
    indirme thread'i aynı oturumu paylaştığı için yenileme kilitli.
    """

    def __init__(
        self,
        email: str,
        refresh_token: str,
        *,
        client: Client | None = None,
        access_token: str | None = None,
        expires_in: float | None = None,
        post: Post = post_form,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.email = email
        self._refresh_token = refresh_token
        self._client = client
        self._post = post
        self._clock = clock
        self._access = access_token
        self._expiry = clock() + expires_in if access_token and expires_in else 0.0
        self._lock = threading.Lock()
        #: Token geri alındı ya da silindi: bu oturumla bir daha istek yok.
        self.dead = False

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = load_client()
        return self._client

    def access_token(self) -> str:
        with self._lock:
            if self.dead:
                raise AuthError("auth.err.expired")
            if not self._access or self._clock() >= self._expiry - EXPIRY_MARGIN_S:
                self._refresh_locked()
            return self._access or ""

    def refresh(self, stale: str) -> None:
        with self._lock:
            if self.dead:
                raise AuthError("auth.err.expired")
            if self._access and self._access != stale:
                return  # başka bir thread az önce yeniledi
            self._refresh_locked()

    def _refresh_locked(self) -> None:
        client = self.client
        status, body = self._post(TOKEN_URL, {
            "client_id": client.id,
            "client_secret": client.secret,
            "refresh_token": self._refresh_token,
            "grant_type": "refresh_token",
        })
        if status == 200 and isinstance(body.get("access_token"), str):
            if "scope" in body:
                try:
                    require_drive(body)
                except AuthError:
                    self._forget_locked()
                    raise
            self._access = body["access_token"]
            expires = body.get("expires_in")
            self._expiry = self._clock() + (float(expires) if isinstance(expires, (int, float)) else 3600.0)
            return
        error = str(body.get("error") or "")
        if error == "invalid_grant":
            # Refresh token öldü: kullanıcı erişimi geri aldı, parolasını
            # değiştirdi ya da token uzun süre kullanılmadı. Saklamak bir şey
            # kazandırmaz; her açılışta aynı hatayı verirdi.
            self._forget_locked()
            raise AuthError("auth.err.expired")
        raise DriveError("auth.err.token", error=error or status)

    def forget(self) -> None:
        with self._lock:
            self._forget_locked()

    def _forget_locked(self) -> None:
        self.dead = True
        self._access = None
        delete_stored(self.email)

    def save(self) -> None:
        kind, blob = protect(self._refresh_token)
        path = account_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"email": self.email, "koruma": kind, "refresh": blob}
        temp = path.with_name(path.name + ".part")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp, path)


def load_session(post: Post = post_form) -> Session | None:
    """Bağlı hesabı diskten açar; yoksa, bozuksa ya da çözülemiyorsa None
    (ör. dosya başka bir Windows kullanıcısından kopyalanmış)."""
    try:
        data = json.loads(account_path().read_text(encoding="utf-8"))
        email, kind, blob = data["email"], data["koruma"], data["refresh"]
        if not (isinstance(email, str) and email and isinstance(blob, str)):
            return None
        return Session(email, unprotect(kind, blob), post=post)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def delete_stored(email: str | None = None) -> None:
    """Saklanan token'ı siler. `email` verildiyse yalnızca o hesabınkini:
    arka planda ölen eski bir oturum, bu arada girilmiş yeni hesabı silmesin."""
    path = account_path()
    if email is not None:
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("email") != email:
                return
        except (OSError, ValueError, AttributeError):
            pass
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def sign_out(session: Session, post: Post = post_form, wait: bool = False) -> None:
    """Çıkış: token diskten ve bellekten siliniyor, hesabın önbelleği ve
    imleci gidiyor — aynı bilgisayarda başka biri kendi hesabıyla temiz
    girebilsin. Drive'daki dosyalara dokunulmuyor.

    Token Google'da da iptal ediliyor, ama arka planda: ağ yoksa ya da yavaşsa
    pencere beklemesin, çevrimdışı çıkış da mümkün olsun. İptal başarısız
    olursa izin Google hesap ayarlarından kaldırılabilir; token zaten bu
    bilgisayarda kalmadı.
    """
    token = session._refresh_token
    session.forget()
    AccountCache(session.email).clear()

    def revoke() -> None:
        try:
            post(REVOKE_URL, {"token": token})
        except DriveError:
            pass

    if wait:
        revoke()
    else:
        threading.Thread(target=revoke, name="TokenRevoke", daemon=True).start()


# --- Tarayıcıyla giriş --------------------------------------------------------------


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge.rstrip(b"=").decode("ascii")


def _page(message: str) -> bytes:
    title = html.escape(i18n.t("app.title"))
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title></head>"
        "<body style='font-family:Segoe UI,sans-serif;background:#0f1318;color:#e6e9ee;"
        "display:flex;align-items:center;justify-content:center;height:90vh'>"
        f"<p style='max-width:32em;font-size:1.1em;line-height:1.5'>{html.escape(message)}</p>"
        "</body></html>"
    ).encode("utf-8")


def sign_in(
    cancel: threading.Event,
    *,
    client: Client | None = None,
    open_browser: Callable[[str], bool] = webbrowser.open,
    post: Post = post_form,
    timeout_s: float = SIGN_IN_TIMEOUT_S,
) -> Session:
    """Tarayıcı + loopback + PKCE (§1). ARKA THREAD'de çağrılır.

    `prompt=consent select_account`: her girişte hesap seçimi (aynı
    bilgisayarda başka biri girebilsin) ve onay ekranı (refresh token her
    seferinde gelsin). Başarılı olursa oturum diske yazılmış olarak döner.
    """
    client = client or load_client()
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(16)
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if query.get("state") != state:
                # Tarayıcının favicon isteği ya da başka bir sekme: yok say.
                self.send_response(404)
                self.end_headers()
                return
            result.update(query)
            if "code" in query:
                message = i18n.t("account.browser_done")
            else:
                message = i18n.t("account.browser_failed", error=query.get("error", "?"))
            body = _page(message)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    # Yalnızca 127.0.0.1: dinleyici ağdan görünmesin. Port işletim
    # sisteminden; masaüstü istemcisinde Google her portu kabul ediyor.
    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.25
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client.id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent select_account",
    })
    try:
        if not open_browser(url):
            raise DriveError("auth.err.browser")
        deadline = time.monotonic() + timeout_s
        while not result:
            if cancel.is_set():
                raise DriveError("auth.err.cancelled")
            if time.monotonic() > deadline:
                raise DriveError("auth.err.timeout")
            server.handle_request()
    finally:
        server.server_close()

    if "code" not in result:
        raise DriveError("auth.err.denied", error=result.get("error", "?"))

    status, tokens = post(TOKEN_URL, {
        "client_id": client.id,
        "client_secret": client.secret,
        "code": result["code"],
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect,
    })
    if status != 200 or not isinstance(tokens.get("access_token"), str):
        raise DriveError("auth.err.token", error=tokens.get("error") or status)
    require_drive(tokens)
    refresh_token = tokens.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise DriveError("auth.err.no_refresh")
    email = email_of(tokens)
    if not email:
        raise DriveError("auth.err.no_email")

    expires = tokens.get("expires_in")
    session = Session(
        email,
        refresh_token,
        client=client,
        access_token=tokens["access_token"],
        expires_in=float(expires) if isinstance(expires, (int, float)) else 3600.0,
        post=post,
    )
    try:
        session.save()
    except OSError as e:
        raise DriveError("auth.err.store", error=e) from e
    return session
