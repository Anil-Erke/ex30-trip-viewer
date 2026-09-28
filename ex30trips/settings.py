"""Kalıcı kullanıcı tercihleri (şimdilik yalnızca arayüz dili).

Drive ayarlarıyla aynı klasörde, ayrı bir dosyada tutuluyor: `drive.json`
anahtar içeriyor ve kullanıcı onu elle silebilmeli; dil seçimi onunla birlikte
gitmesin.

Tek dosya kipinde exe her açılışta geçici klasöre açıldığı için ayar exe'nin
yanında tutulamıyor — bkz. `drive.config_dir`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .drive import config_dir


def settings_path() -> Path:
    return config_dir() / "settings.json"


def load() -> dict[str, Any]:
    """Ayarları okur. Dosya yoksa ya da bozuksa boş sözlük — açılış hiç düşmez."""
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save(**changes: Any) -> None:
    """Verilen alanları mevcut ayarların üstüne yazar. Hata yutulmaz."""
    data = load()
    data.update(changes)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
