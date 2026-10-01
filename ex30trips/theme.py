"""Tek bir renk paleti: hem ttk widget'ları hem matplotlib figürleri buradan beslenir.

Matplotlib'in kendi koyu stilini kullanmıyoruz; grafik arka planı ile pencere
arka planı birbirini tutmazsa gömülü tuval yamalı görünüyor.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

BG = "#13161b"          # pencere zemini
PANEL = "#1a1e25"       # kart / tablo zemini
PANEL_ALT = "#222833"   # seçili satır, başlık
LINE = "#2d343f"        # ayraç ve ızgara
TEXT = "#e7e9ee"
MUTED = "#98a2b3"

ACCENT = "#4ea1ff"      # tüketim / ana seri
GREEN = "#43c78a"       # rejen, kazanç
ORANGE = "#ffb454"      # uyarı, hız
RED = "#ff6b6b"         # kayıp, düşüş
PURPLE = "#b48ef6"      # menzil
CYAN = "#3fd0d6"        # ikincil seri

#: Sıcaklık bantlarının rengi (stats.BANDS ile aynı sırada).
BAND_COLORS = (CYAN, ACCENT, GREEN, ORANGE)

FONT = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_TITLE = ("Segoe UI Semibold", 12)
FONT_KPI = ("Segoe UI Semibold", 17)


def apply(root: tk.Misc) -> ttk.Style:
    """Koyu temayı kurar. 'clam' seçiliyor: renkleri gerçekten uygulayan tek tema."""
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=BG, foreground=TEXT, font=FONT, borderwidth=0)
    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT_SMALL)
    style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED, font=FONT_SMALL)
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=FONT_TITLE)
    style.configure("Kpi.TLabel", background=PANEL, foreground=TEXT, font=FONT_KPI)
    style.configure("KpiAccent.TLabel", background=PANEL, foreground=ACCENT, font=FONT_KPI)

    style.configure(
        "TButton",
        background=PANEL_ALT,
        foreground=TEXT,
        padding=(12, 6),
        focuscolor=PANEL_ALT,
    )
    style.map(
        "TButton",
        background=[("pressed", ACCENT), ("active", "#2c3440")],
        # Devre dışı düğme soluk: hesap penceresinde Giriş/Çıkış'tan hangisinin
        # geçerli olduğu yalnızca buradan anlaşılıyor.
        foreground=[("disabled", MUTED), ("pressed", "#0b0e12")],
    )

    style.configure("TSeparator", background=LINE)
    style.configure("TLabelframe", background=BG, foreground=MUTED, bordercolor=LINE)
    style.configure("TLabelframe.Label", background=BG, foreground=MUTED, font=FONT_SMALL)

    style.configure(
        "TCombobox",
        fieldbackground=PANEL_ALT,
        background=PANEL_ALT,
        foreground=TEXT,
        arrowcolor=MUTED,
        selectbackground=PANEL_ALT,
        selectforeground=TEXT,
        padding=(8, 4),
    )
    style.map("TCombobox", fieldbackground=[("readonly", PANEL_ALT)])
    # Açılır listenin kendisi ttk değil; Tk seçenek veritabanından boyanıyor.
    root.option_add("*TCombobox*Listbox.background", PANEL_ALT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#0b0e12")

    style.configure(
        "Treeview",
        background=PANEL,
        fieldbackground=PANEL,
        foreground=TEXT,
        rowheight=26,
        borderwidth=0,
    )
    style.map(
        "Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", "#0b0e12")],
    )
    style.configure(
        "Treeview.Heading",
        background=PANEL_ALT,
        foreground=MUTED,
        font=FONT_SMALL,
        relief="flat",
        padding=(6, 6),
    )
    style.map("Treeview.Heading", background=[("active", LINE)])

    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
    style.configure(
        "TNotebook.Tab",
        background=BG,
        foreground=MUTED,
        padding=(16, 8),
        font=FONT_SMALL,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", PANEL)],
        foreground=[("selected", TEXT)],
    )

    style.configure(
        "Vertical.TScrollbar",
        background=PANEL_ALT,
        troughcolor=BG,
        arrowcolor=MUTED,
        bordercolor=BG,
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=PANEL_ALT,
        troughcolor=BG,
        arrowcolor=MUTED,
        bordercolor=BG,
    )
    return style


def mpl_rc() -> dict[str, object]:
    """Figürlerin rcParams'ı. Her figür oluşturulurken uygulanır."""
    return {
        "figure.facecolor": PANEL,
        "axes.facecolor": PANEL,
        "savefig.facecolor": PANEL,
        "axes.edgecolor": LINE,
        "axes.labelcolor": MUTED,
        "axes.titlecolor": TEXT,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "axes.labelsize": 9,
        "axes.grid": True,
        # Izgara barlarin ustune degil altina: dolu barlarda cizgi kirli duruyor.
        "axes.axisbelow": True,
        "grid.color": LINE,
        "grid.linewidth": 0.7,
        "grid.alpha": 0.9,
        "text.color": TEXT,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.facecolor": PANEL_ALT,
        "legend.edgecolor": LINE,
        "legend.fontsize": 8,
        "legend.labelcolor": TEXT,
        "font.family": "Segoe UI",
        "font.size": 9,
    }
