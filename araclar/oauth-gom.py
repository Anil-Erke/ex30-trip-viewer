"""Masaüstü OAuth istemcisini derlemeye gömer: `oauth.properties` → `ex30trips/_oauth.py`.

`exe-olustur.ps1` derlemeden önce çağırıyor. Tek dosya exe'de yanında bir
`oauth.properties` taşımak yerine değerler modül olarak pakete giriyor.
Google masaüstü uygulamalarında istemci kimliğini ve sırrını gizli saymıyor
(tek başlarına hiçbir veriye erişim vermiyorlar); yine de DEPOYA GİRMİYORLAR:
hem kaynak dosya hem üretilen `_oauth.py` `.gitignore`'da.

Aranan yerler (ilk bulunan): `EX30_OAUTH_PROPERTIES` ortam değişkeni, proje
kökü, yan klasördeki `EX30 Telemetry/oauth.properties`.

Çalıştırma:  py -3 araclar/oauth-gom.py [oauth.properties yolu]
Çıkış kodu:  0 yazıldı · 1 dosya ya da değer bulunamadı
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ex30trips.auth import _properties_candidates, read_properties  # noqa: E402

OUTPUT = ROOT / "ex30trips" / "_oauth.py"


def main() -> int:
    candidates = [Path(sys.argv[1])] if len(sys.argv) > 1 else _properties_candidates()
    for path in candidates:
        client = read_properties(path)
        if client is None:
            continue
        OUTPUT.write_text(
            "# Derleme sırasında araclar/oauth-gom.py üretti — DEPOYA GİRMEZ (.gitignore).\n"
            f"# Kaynak: {path.name}\n"
            f"CLIENT_ID = {client.id!r}\n"
            f"CLIENT_SECRET = {client.secret!r}\n",
            encoding="utf-8",
        )
        # Sır ekrana basılmıyor; kimliğin başı hangi istemcinin gömüldüğünü
        # anlamaya yetiyor.
        print(f"ok: {path} -> {OUTPUT.name} (istemci {client.id[:12]}…)")
        return 0
    print("oauth.properties bulunamadı ya da desktopClientId/desktopClientSecret eksik. Arananlar:")
    for path in candidates:
        print(f"  {path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
