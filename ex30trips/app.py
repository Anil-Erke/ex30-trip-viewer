"""EX30 Yolculuk Görüntüleyici — Tkinter penceresi.

Sol tarafta filtrelenmiş yolculuk listesi ve özet kartları, sağ tarafta
matplotlib sekmeleri var. Seçilen yolculuk hem detay sekmesinde açılıyor hem de
grafiklerde vurgulanıyor.

Kaynaklar birikir, birbirinin yerine geçmez: Drive'dan inen son günlerin üstüne
eski kayıtların durduğu bir klasör eklenebilir, ekrandaki liste ikisinin
birleşimidir (`loader.combine`). Hepsini bırakmak için "Temizle", tek bir
kaynağı çıkarmak için "Yüklü kaynaklar…" var.

Çizim maliyeti: sekme değişmeden yeniden çizim yapılmıyor. Filtre ya da seçim
değiştiğinde bütün sekmeler "kirli" işaretlenip yalnızca görünen sekme çiziliyor.

Dil (Türkçe / İngilizce) çalışırken değişebiliyor: widget'lar yıkılıp yeni dille
kuruluyor, veriler ve ekran durumu yerinde kalıyor (`set_language`). Kullanıcıya
görünen her metin `t()` üzerinden gelir; bu modülde düz Türkçe dizge yok. Bu
yüzden yerel değişkenlere `t` adı verilmiyor — yolculuk değişkeni `trip`.
"""

from __future__ import annotations

import csv
import queue
import sys
import threading
import tkinter as tk

from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")

from matplotlib.backends.backend_tkagg import (  # noqa: E402
    FigureCanvasTkAgg,
    NavigationToolbar2Tk,
)
from matplotlib.figure import Figure  # noqa: E402

from . import charts, drive, i18n, settings, stats, theme  # noqa: E402
from .i18n import num, t  # noqa: E402
from .loader import LoadResult, Source, combine, load  # noqa: E402
from .model import Trip  # noqa: E402


class DriveSettingsDialog(tk.Toplevel):
    """Drive ucunun adresi ve okuma anahtarı.

    Değerler `%LOCALAPPDATA%` altındaki ayar dosyasına yazılıyor; kaynağa ya da
    exe'ye gömülmüyorlar. Anahtar alanı maskeli: ekran paylaşımında ya da
    ekran görüntüsünde kazara görünmesin.
    """

    def __init__(self, parent: tk.Misc, config: drive.Config) -> None:
        super().__init__(parent)
        self.result: drive.Config | None = None

        self.title(t("drive.settings.title"))
        self.resizable(False, False)
        self.transient(parent)

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=t("drive.settings.intro"),
            style="Muted.TLabel",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        ttk.Label(frame, text=t("drive.settings.url")).grid(row=1, column=0, sticky="w", padx=(0, 10))
        self.url_var = tk.StringVar(value=config.url)
        url_entry = ttk.Entry(frame, textvariable=self.url_var, width=62)
        url_entry.grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(frame, text=t("drive.settings.secret")).grid(row=2, column=0, sticky="w", padx=(0, 10))
        self.secret_var = tk.StringVar(value=config.secret)
        ttk.Entry(frame, textvariable=self.secret_var, width=62, show="•").grid(
            row=2, column=1, sticky="ew", pady=4
        )

        ttk.Label(
            frame,
            text=t("drive.settings.path", path=drive.config_path()),
            style="Muted.TLabel",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text=t("common.cancel"), command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text=t("common.save"), command=self._save).pack(side="right")

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())

        url_entry.focus_set()
        self.grab_set()
        self.wait_window(self)

    def _save(self) -> None:
        config = drive.Config(url=self.url_var.get().strip(), secret=self.secret_var.get().strip())
        if not config.ready:
            messagebox.showwarning(t("app.title"), t("drive.settings.both_required"), parent=self)
            return
        try:
            drive.save_config(config)
        except OSError as e:
            messagebox.showerror(t("app.title"), t("drive.settings.save_failed", error=e), parent=self)
            return
        self.result = config
        self.destroy()


class SourcesDialog(tk.Toplevel):
    """Yüklü kaynakların listesi.

    "Temizle" hepsini bırakıyor; burası yanlış eklenen tek bir klasörü çıkarıp
    geri kalanları yerinde tutmak için. Kaldırma kalan kaynakları yeniden
    okumuyor, yalnızca birleşimi baştan hesaplıyor.
    """

    def __init__(self, parent: "TripViewer") -> None:
        super().__init__(parent)
        self.app = parent

        self.title(t("sources.title"))
        self.transient(parent)
        self.geometry("720x320")
        self.configure(background=theme.BG)

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=t("sources.intro"),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        wrap = ttk.Frame(frame, style="Panel.TFrame", padding=1)
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            wrap,
            columns=("kind", "label", "files", "trips"),
            show="headings",
            selectmode="browse",
        )
        for key, title_key, width, anchor in (
            ("kind", "sources.col.kind", 90, "w"),
            ("label", "sources.col.label", 410, "w"),
            ("files", "sources.col.files", 60, "e"),
            ("trips", "sources.col.trips", 80, "e"),
        ):
            self.tree.heading(key, text=t(title_key), anchor=anchor)
            self.tree.column(key, width=width, anchor=anchor, stretch=(key == "label"))
        self.tree.tag_configure("odd", background=theme.PANEL_ALT)
        self.tree.pack(fill="both", expand=True)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        self.remove_button = ttk.Button(buttons, text=t("sources.remove"), command=self._remove)
        self.remove_button.pack(side="left")
        ttk.Button(buttons, text=t("sources.clear_all"), command=self._clear).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text=t("common.close"), command=self.destroy).pack(side="right")

        self._fill()
        self.bind("<Escape>", lambda _e: self.destroy())

    def _fill(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, source in enumerate(self.app.sources):
            # Tek yollu kaynakta tam yol gösteriliyor: iki ayrı klasörün adı
            # aynı olabiliyor ("disaaktarim"), hangisi olduğu yoldan anlaşılır.
            where = str(source.paths[0]) if len(source.paths) == 1 else source.label
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                tags=("odd",) if index % 2 else (),
                values=(
                    source_kind_label(source.kind),
                    where,
                    len(source.result.files),
                    len(source.result.trips),
                ),
            )
        self.remove_button.state(["!disabled"] if self.app.sources else ["disabled"])

    def _remove(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        self.app.remove_source(int(selection[0]))
        self._fill()

    def _clear(self) -> None:
        self.app.clear_sources()
        self._fill()


class ChartToolbar(NavigationToolbar2Tk):
    """Matplotlib araç çubuğunun kısaltılmışı.

    İleri/geri düğmeleri geçmiş boşken devre dışı geliyor ve Windows onları
    damalı bir maskeyle çiziyor — koyu temada leke gibi duruyor. Ev, kaydır,
    büyüt ve kaydet yeterli.
    """

    toolitems = tuple(
        item
        for item in NavigationToolbar2Tk.toolitems
        if item[0] in ("Home", "Pan", "Zoom", "Save")
    )


#: Filtre: dil anahtarı → gün sayısı (None = sınırsız).
PERIODS: tuple[tuple[str, int | None], ...] = (
    ("period.all", None),
    ("period.7", 7),
    ("period.30", 30),
    ("period.90", 90),
    ("period.365", 365),
)

#: Filtre: en az mesafe (km); 0 = hepsi. Etiket `distance_label` ile kuruluyor.
MIN_DISTANCES: tuple[float, ...] = (0.0, 1.0, 5.0, 20.0)


def distance_label(km: float) -> str:
    return t("distance.all") if km <= 0 else f"≥ {num(km, 0)} km"


def source_kind_label(kind: str) -> str:
    """Kaynak türünün görünen adı (lang: source.kind.<tür>)."""
    key = f"source.kind.{kind}"
    return t(key) if i18n.has(key) else kind


def resource_path(relative: str) -> Path:
    """Pakete gömülü dosyanın yolu.

    PyInstaller exe'si çalışırken kaynaklar geçici bir klasöre açılıyor ve
    `sys._MEIPASS` oraya işaret ediyor; kaynaktan çalışırken proje kökü geçerli.
    İkisini burada ayırmazsak exe'de "Örnek veri" düğmesi dosyayı bulamıyor.
    """
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent.parent
    return root.joinpath(*relative.split("/"))


class TripViewer(tk.Tk):
    #: Sol sütunun (özet + tablo) başlangıç genişliği.
    LEFT_WIDTH = 570

    def __init__(self, initial_paths: list[Path] | None = None) -> None:
        super().__init__()
        self.title(t("app.title"))
        self.geometry("1360x860")
        self.minsize(1080, 700)
        self.configure(background=theme.BG)

        matplotlib.rcParams.update(theme.mpl_rc())
        theme.apply(self)

        self.all_trips: list[Trip] = []
        self.trips: list[Trip] = []          # filtrelenmiş, zamana göre artan
        self.selected: int | None = None     # self.trips içindeki sıra
        #: Yüklü kaynaklar ekleme sırasıyla; `all_trips` hepsinin birleşimi.
        self.sources: list[Source] = []
        self._dirty: set[int] = set()
        self._figures: dict[int, Figure] = {}
        self._canvases: dict[int, FigureCanvasTkAgg] = {}
        self._sort_column = "start"
        self._sort_reverse = True
        #: Drive indirmesi arka thread'de; sonuç buradan ana thread'e geçiyor.
        self._drive_queue: queue.Queue[tuple[Path | None, str | None]] = queue.Queue()
        self._drive_busy = False
        #: Dil menüsündeki işaretli düğme; yeniden kurulumlar arasında yaşıyor.
        self.language_var = tk.StringVar(value=i18n.language())

        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._build_body()

        self.bind("<Control-o>", lambda _e: self.open_files())
        self.bind("<Control-d>", lambda _e: self.fetch_from_drive())
        self.bind("<F5>", lambda _e: self.reload())

        if initial_paths:
            self.add_paths(initial_paths, "cli")
        else:
            self._refresh()

    # --- Arayüz kurulumu -----------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self, background=theme.PANEL, foreground=theme.TEXT, borderwidth=0)
        opts = dict(
            background=theme.PANEL,
            foreground=theme.TEXT,
            activebackground=theme.ACCENT,
            activeforeground="#0b0e12",
            borderwidth=0,
        )
        file_menu = tk.Menu(menubar, tearoff=0, **opts)
        # "aç" değil "ekle": her seçim yüklü kaynakların üstüne biniyor.
        file_menu.add_command(label=t("menu.add_files"), command=self.open_files)
        file_menu.add_command(label=t("menu.add_folder"), command=self.open_folder)
        file_menu.add_command(label=t("menu.add_sample"), command=self.open_sample)
        file_menu.add_separator()
        file_menu.add_command(label=t("menu.drive_fetch"), command=self.fetch_from_drive)
        file_menu.add_command(label=t("menu.drive_settings"), command=self.edit_drive_settings)
        file_menu.add_separator()
        file_menu.add_command(label=t("menu.sources"), command=self.show_sources)
        file_menu.add_command(label=t("menu.clear"), command=self.clear_sources)
        file_menu.add_command(label=t("menu.reload"), command=self.reload)
        file_menu.add_separator()
        file_menu.add_command(label=t("menu.export_csv"), command=self.export_csv)
        file_menu.add_command(label=t("menu.export_png"), command=self.export_png)
        file_menu.add_separator()
        file_menu.add_command(label=t("menu.exit"), command=self.destroy)
        menubar.add_cascade(label=t("menu.file"), menu=file_menu)

        # Menü başlığı iki dilli ("Dil / Language"), dil adları kendi dillerinde:
        # yanlış dilde açılan uygulamada da geri dönüş yolu bulunabilsin.
        language_menu = tk.Menu(menubar, tearoff=0, **opts)
        for code, name in i18n.LANGUAGES.items():
            language_menu.add_radiobutton(
                label=name,
                value=code,
                variable=self.language_var,
                command=lambda c=code: self.set_language(c),
            )
        menubar.add_cascade(label=t("menu.language"), menu=language_menu)

        help_menu = tk.Menu(menubar, tearoff=0, **opts)
        help_menu.add_command(label=t("menu.help_source"), command=self.show_help)
        help_menu.add_command(label=t("menu.about"), command=self.show_about)
        menubar.add_cascade(label=t("menu.help"), menu=help_menu)
        self.config(menu=menubar)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(14, 12, 14, 8))
        bar.pack(side="top", fill="x")

        ttk.Label(bar, text=t("app.title"), style="Title.TLabel").pack(side="left")
        # Alt başlık kısa: clam temasında her düğme en az 103 px yer kaplıyor ve
        # "Temizle" eklenince uzun hâli araç çubuğunu 1360 px'lik varsayılan
        # pencereden taşırıyordu — sağdaki CSV düğmesi filtrenin üstüne biniyor.
        ttk.Label(bar, text="  Volvo EX30", style="Muted.TLabel").pack(
            side="left", padx=(6, 16)
        )

        ttk.Button(bar, text=t("toolbar.add_files"), command=self.open_files).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text=t("toolbar.add_folder"), command=self.open_folder).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text=t("toolbar.sample"), command=self.open_sample).pack(side="left", padx=(0, 6))
        self.drive_button = ttk.Button(bar, text=t("toolbar.drive"), command=self.fetch_from_drive)
        # Dil değişip araç çubuğu yeniden kurulduğunda süren indirme unutulmasın.
        if self._drive_busy:
            self.drive_button.state(["disabled"])
        self.drive_button.pack(side="left", padx=(0, 6))
        # Yüklü kaynak yokken temizlenecek bir şey de yok.
        self.clear_button = ttk.Button(bar, text=t("toolbar.clear"), command=self.clear_sources)
        self.clear_button.state(["disabled"])
        self.clear_button.pack(side="left", padx=(0, 18))

        ttk.Label(bar, text=t("toolbar.period"), style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.period_box = ttk.Combobox(
            bar,
            state="readonly",
            width=13,
            values=[t(key) for key, _days in PERIODS],
        )
        self.period_box.current(0)
        self.period_box.pack(side="left", padx=(0, 14))
        self.period_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh())

        ttk.Label(bar, text=t("toolbar.distance"), style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.distance_box = ttk.Combobox(
            bar, state="readonly", width=9, values=[distance_label(km) for km in MIN_DISTANCES]
        )
        self.distance_box.current(0)
        self.distance_box.pack(side="left")
        self.distance_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh())

        ttk.Button(bar, text=t("toolbar.export_csv"), command=self.export_csv).pack(side="right")

    def _build_body(self) -> None:
        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.pack(side="top", fill="both", expand=True, padx=14, pady=(0, 8))

        # Genişlik bölmenin kendisinde sabit ve yayılım kapalı: bölmenin istenen
        # genişliği budur, sash oraya oturur. `sashpos` ile elle yerleştirmeyi
        # denemiyoruz — pencere son boyutuna gelmeden çağrıldığında değeri
        # kırpıyor ve sol sütun sıfıra iniyor. weight=0 sayesinde pencere
        # büyüdükçe fazla genişlik grafiklere gidiyor, sol sütun sabit kalıyor.
        left = ttk.Frame(pane, width=self.LEFT_WIDTH)
        left.pack_propagate(False)
        pane.add(left, weight=0)
        self._build_kpis(left)
        self._build_table(left)

        right = ttk.Frame(pane)
        pane.add(right, weight=1)
        self._build_tabs(right)


    def _build_kpis(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=(14, 12))
        card.pack(side="top", fill="x", pady=(0, 8))

        self.kpi_labels: dict[str, ttk.Label] = {}
        # Birim değerin yanında değil etikette: 570 px'lik sütunda dört kart
        # yan yana duruyor, "14,0 kWh/100 km" taşıyor.
        fields = (
            ("trips", "kpi.trips"),
            ("km", "kpi.km"),
            ("duration", "kpi.duration"),
            ("consumption", "kpi.consumption"),
            ("energy", "kpi.energy"),
            ("regen", "kpi.regen"),
            ("speed", "kpi.speed"),
            ("bias", "kpi.bias"),
        )
        for i, (key, label) in enumerate(fields):
            row, col = divmod(i, 4)
            cell = ttk.Frame(card, style="Panel.TFrame")
            cell.grid(row=row, column=col, sticky="w", padx=(0, 18), pady=(0, 10))
            value = ttk.Label(
                cell,
                text="—",
                style="KpiAccent.TLabel" if key in ("km", "consumption") else "Kpi.TLabel",
            )
            value.pack(anchor="w")
            ttk.Label(cell, text=t(label), style="PanelMuted.TLabel").pack(anchor="w")
            self.kpi_labels[key] = value
        for col in range(4):
            card.columnconfigure(col, weight=1, uniform="kpi")

    def _build_table(self, parent: ttk.Frame) -> None:
        wrap = ttk.Frame(parent, style="Panel.TFrame", padding=1)
        wrap.pack(side="top", fill="both", expand=True)

        columns = (
            ("start", "col.start", 112, "w"),
            ("duration", "col.duration", 86, "e"),
            ("km", "col.km", 56, "e"),
            ("consumption", "col.consumption", 64, "e"),
            ("energy", "col.energy", 52, "e"),
            ("soc", "col.soc", 52, "e"),
            ("speed", "col.speed", 58, "e"),
            ("temp", "col.temp", 40, "e"),
        )
        self.tree = ttk.Treeview(
            wrap, columns=[c[0] for c in columns], show="headings", selectmode="browse"
        )
        for key, title, width, anchor in columns:
            self.tree.heading(key, text=t(title), command=lambda k=key: self._sort_by(k))
            self.tree.column(key, width=width, anchor=anchor, stretch=(key == "start"))
        self.tree.tag_configure("odd", background=theme.PANEL_ALT)

        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _e: self.tabs.select(len(charts.CHARTS)))

    def _build_tabs(self, parent: ttk.Frame) -> None:
        self.tabs = ttk.Notebook(parent)
        self.tabs.pack(fill="both", expand=True)

        for index, (title_key, _fn) in enumerate(charts.CHARTS):
            frame = ttk.Frame(self.tabs, style="Panel.TFrame")
            self.tabs.add(frame, text=t(title_key))
            figure = Figure(figsize=(8, 6), dpi=100, layout="constrained")
            canvas = FigureCanvasTkAgg(figure, master=frame)
            canvas.get_tk_widget().configure(background=theme.PANEL, highlightthickness=0)
            toolbar = ChartToolbar(canvas, frame, pack_toolbar=False)
            toolbar.update()
            self._style_toolbar(toolbar)
            toolbar.pack(side="bottom", fill="x")
            canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
            self._figures[index] = figure
            self._canvases[index] = canvas

        self._build_detail_tab()
        self.tabs.bind("<<NotebookTabChanged>>", lambda _e: self._draw_current())

    def _style_toolbar(self, toolbar: NavigationToolbar2Tk) -> None:
        """Matplotlib araç çubuğu ttk değil; renklerini elle veriyoruz.

        Düğme resimleri saydam: arka plan verilmezse koyu temada damalı görünüyor.
        """
        try:
            toolbar.configure(background=theme.PANEL, borderwidth=0)
        except tk.TclError:
            return
        for child in toolbar.winfo_children():
            options = child.keys()
            settings: dict[str, object] = {}
            for name, value in (
                ("background", theme.PANEL),
                ("activebackground", theme.PANEL_ALT),
                ("selectcolor", theme.PANEL_ALT),
                ("highlightbackground", theme.PANEL),
                ("borderwidth", 0),
                ("highlightthickness", 0),
                ("relief", "flat"),
            ):
                if name in options:
                    settings[name] = value
            if isinstance(child, tk.Label) and "foreground" in options:
                settings["foreground"] = theme.MUTED
            try:
                child.configure(**settings)
            except tk.TclError:
                pass

    def _build_detail_tab(self) -> None:
        frame = ttk.Frame(self.tabs, style="Panel.TFrame", padding=(16, 14))
        self.tabs.add(frame, text=t("tab.detail"))

        self.detail_title = ttk.Label(frame, text=t("detail.none"), style="Kpi.TLabel")
        self.detail_title.pack(anchor="w")
        self.detail_sub = ttk.Label(frame, text="", style="PanelMuted.TLabel")
        self.detail_sub.pack(anchor="w", pady=(0, 12))

        table = ttk.Frame(frame, style="Panel.TFrame")
        table.pack(fill="both", expand=True)
        self.detail_tree = ttk.Treeview(
            table, columns=("field", "value"), show="headings", selectmode="none"
        )
        self.detail_tree.heading("field", text=t("detail.col.field"), anchor="w")
        self.detail_tree.heading("value", text=t("detail.col.value"), anchor="w")
        self.detail_tree.column("field", width=280, anchor="w")
        self.detail_tree.column("value", width=240, anchor="w")
        self.detail_tree.tag_configure("odd", background=theme.PANEL_ALT)
        self.detail_tree.tag_configure("group", foreground=theme.MUTED)
        # Alan sayısı pencereye sığmıyor: kaydırma olmadan son satırlar
        # (rakım, performans ölçümleri) hiç görünmüyordu.
        detail_scroll = ttk.Scrollbar(table, orient="vertical", command=self.detail_tree.yview)
        self.detail_tree.configure(yscrollcommand=detail_scroll.set)
        self.detail_tree.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, padding=(14, 6, 14, 10))
        bar.pack(side="bottom", fill="x")
        self.status = ttk.Label(
            bar,
            text=t("status.empty"),
            style="Muted.TLabel",
        )
        self.status.pack(side="left")
        # Kaç kaynağın yüklü olduğunu yazan yer, onları görmek istemenin de
        # doğal yeri: tıklayınca kaynak listesi açılıyor.
        self.file_status = ttk.Label(bar, text="", style="Muted.TLabel", cursor="hand2")
        self.file_status.pack(side="right")
        self.file_status.bind("<Button-1>", lambda _e: self.show_sources())

    # --- Dil -----------------------------------------------------------------

    def set_language(self, code: str) -> None:
        """Arayüz dilini değiştirir ve seçimi kalıcı yapar.

        Pencere kapanıp açılmıyor: widget'lar yıkılıp yeni dille yeniden
        kuruluyor. Yüklü kaynaklar, filtreler, sıralama, seçili yolculuk ve
        açık sekme yerinde kalıyor; hiçbir dosya yeniden okunmuyor.
        """
        if code == i18n.language():
            return
        i18n.set_language(code)
        self.language_var.set(code)
        try:
            settings.save(language=code)
        except OSError:
            # Kaydedilemese de bu oturumda dil değişsin; bir sonraki açılış
            # önceki dille gelir, o kadar.
            pass
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        period = self.period_box.current()
        distance = self.distance_box.current()
        tab = self.tabs.index(self.tabs.select())

        # Menü çubuğu da pencerenin çocuğu; o da yeni dille kuruluyor. Açık bir
        # "Yüklü kaynaklar" penceresi de kapanıyor — eski dilde kalmasın.
        for child in self.winfo_children():
            child.destroy()
        self._figures.clear()
        self._canvases.clear()

        self.title(t("app.title"))
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._build_body()

        self.period_box.current(period)
        self.distance_box.current(distance)
        self._recombine()
        self._refresh()
        # Sekme en son: seçim olayı görünen sekmeyi yeni figürüne çizdiriyor.
        self.tabs.select(tab)

    # --- Veri yükleme --------------------------------------------------------

    def open_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title=t("dialog.pick_files"),
            filetypes=[
                (t("filetype.trips"), "trips*.txt trips*.json"),
                (t("filetype.text"), "*.txt *.json"),
                (t("filetype.all"), "*.*"),
            ],
        )
        if paths:
            self.add_paths([Path(p) for p in paths], "file")

    def open_folder(self) -> None:
        folder = filedialog.askdirectory(title=t("dialog.pick_folder"))
        if folder:
            self.add_paths([Path(folder)], "folder")

    def open_sample(self) -> None:
        sample = resource_path("ornek/trips-ornek.txt")
        if not sample.exists():
            messagebox.showwarning(t("app.title"), t("load.sample_missing", path=sample))
            return
        self.add_paths([sample], "sample")

    def edit_drive_settings(self) -> bool:
        """Ayar penceresini açar. @return kaydedildiyse True."""
        dialog = DriveSettingsDialog(self, drive.load_config())
        return dialog.result is not None

    def fetch_from_drive(self) -> None:
        """Araçtan Drive'a yüklenmiş `trips.json`'u indirip açar.

        Ağ çağrısı ARKA THREAD'de: Tkinter tek thread'li ve indirme ana
        thread'de yapılırsa pencere indirme boyunca donar.

        Sonuç `after` ile değil bir kuyruk üzerinden geri alınıyor. Tkinter
        thread güvenli değil; arka thread'den doğrudan pencereye dokunmak
        (`after` dahil) yer yer çalışıp yer yer çöken bir şey — kuyruğu ana
        thread yokluyor, widget'lara yalnızca o dokunuyor.
        """
        if self._drive_busy:
            return

        config = drive.load_config()
        if not config.ready:
            if not self.edit_drive_settings():
                return
            config = drive.load_config()
            if not config.ready:
                return

        self._drive_busy = True
        self.drive_button.state(["disabled"])
        self.status.config(text=t("status.drive_downloading"))

        def work() -> None:
            try:
                path = drive.download(config)
            except drive.DriveError as e:
                self._drive_queue.put((None, str(e)))
            except Exception as e:  # beklenmedik hata da arayüze ulaşsın
                self._drive_queue.put((None, t("drive.err.unexpected", error=e)))
            else:
                self._drive_queue.put((path, None))

        threading.Thread(target=work, name="DriveFetch", daemon=True).start()
        self.after(150, self._poll_drive)

    def _poll_drive(self) -> None:
        try:
            path, error = self._drive_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_drive)
            return

        self._drive_busy = False
        self.drive_button.state(["!disabled"])

        if error is not None:
            self.status.config(text=t("status.drive_failed"))
            messagebox.showerror(t("app.title"), t("drive.failed", error=error))
            return

        assert path is not None
        # İndirilen dosyanın yolu hep aynı: Drive'dan ikinci kez alındığında
        # yeni bir kaynak eklenmiyor, duran kaynak tazesiyle değişiyor.
        self.add_paths([path], "drive", "Drive (trips.json)")

    def reload(self) -> None:
        """Yüklü bütün kaynakları diskten yeniden okur (F5).

        Kaynağın dosya listesi değil ISTENEN YOLU saklandığı için, klasör
        kaynağına o sırada yeni bir dışa aktarım düşmüşse yenileme onu da alır.
        """
        if not self.sources:
            return
        self.sources = [
            Source(kind=s.kind, label=s.label, paths=s.paths, result=load(list(s.paths)))
            for s in self.sources
        ]
        self._recombine()
        self._refresh()
        self.status.config(text=t("status.reloaded", n=len(self.sources)))

    @staticmethod
    def _label_for(paths: list[Path]) -> str:
        if len(paths) == 1:
            return paths[0].name or str(paths[0])
        return f"{paths[0].name} +{len(paths) - 1}"

    def add_paths(self, paths: list[Path], kind: str = "file", label: str | None = None) -> None:
        """Yeni bir kaynağı yüklü olanların ÜSTÜNE ekler.

        Eklemek yerine değiştirmek, Drive'daki son 10 günü göstermek için eski
        kayıtların durduğu klasörden vazgeçmek demekti. Artık ikisi de listede:
        aynı yolculuk iki kaynakta da varsa `combine` onu tekliyor.

        Aynı yolu ikinci kez seçmek kaynağı çoğaltmıyor, tazesiyle değiştiriyor.
        """
        result: LoadResult = load(paths)
        if not result.trips:
            detail = "\n".join(f"· {p.name}: {why}" for p, why in result.failures)
            parts = [t("load.failed"), detail or t("load.nothing_found")]
            if self.sources:
                parts.append(t("load.kept"))
            messagebox.showerror(t("app.title"), "\n\n".join(parts))
            return

        source = Source(
            kind=kind,
            label=label or self._label_for(paths),
            paths=tuple(paths),
            result=result,
        )
        known = {t.start_epoch for t in self.all_trips}
        for index, existing in enumerate(self.sources):
            if existing.key == source.key:
                self.sources[index] = source
                break
        else:
            self.sources.append(source)

        self._recombine()
        self._refresh()

        fresh = sum(1 for t in self.all_trips if t.start_epoch not in known)
        if self.trips:
            self.status.config(
                text=t(
                    "status.added",
                    label=source.label,
                    fresh=fresh,
                    sources=len(self.sources),
                    total=len(self.all_trips),
                )
            )

    def remove_source(self, index: int) -> None:
        """Tek bir kaynağı çıkarır; geri kalanlar yeniden okunmadan kalır."""
        if not (0 <= index < len(self.sources)):
            return
        dropped = self.sources.pop(index)
        self._recombine()
        self._refresh()
        self.status.config(text=t("status.removed", label=dropped.label, n=len(self.all_trips)))

    def clear_sources(self) -> None:
        """Bütün kaynakları bırakır — ekran ilk açılıştaki hâline döner."""
        if not self.sources:
            return
        self.sources.clear()
        self.selected = None
        self._recombine()
        self._refresh()

    def _recombine(self) -> None:
        """Kaynakların birleşimini ekrana veren tek yer."""
        result = combine(self.sources)
        self.all_trips = result.trips

        self.clear_button.state(["!disabled"] if self.sources else ["disabled"])
        if not self.sources:
            self.file_status.config(text="")
            return

        parts = [
            t("files.sources", n=len(self.sources)),
            t("files.files", n=len(result.files)),
            t("files.trips", n=len(result.trips)),
        ]
        if result.duplicates:
            parts.append(t("files.duplicates", n=result.duplicates))
        if result.failures:
            parts.append(t("files.failures", n=len(result.failures)))
        self.file_status.config(text=" · ".join(parts))

    def show_sources(self) -> None:
        if not self.sources:
            messagebox.showinfo(t("app.title"), t("sources.none"))
            return
        SourcesDialog(self)

    # --- Filtre, tablo, özet -------------------------------------------------

    def _filtered(self) -> list[Trip]:
        trips = list(self.all_trips)
        if not trips:
            return trips

        days = PERIODS[self.period_box.current()][1]
        if days is not None:
            # Referans "bugün" değil, en son yolculuk: eski bir dışa aktarım
            # açıldığında "son 7 gün" boş liste vermemeli.
            newest = max(t.start_epoch for t in trips)
            cutoff = newest - days * 86_400_000
            trips = [t for t in trips if t.start_epoch >= cutoff]

        min_km = MIN_DISTANCES[self.distance_box.current()]
        if min_km > 0:
            trips = [t for t in trips if t.distance_km >= min_km]
        return trips

    def _refresh(self) -> None:
        # Seçim sıra numarasıyla tutuluyor; filtre daralınca eski sıra yeni
        # listenin dışında kalıyordu. Yolculuğun kendisini saklayıp yeniden
        # eşliyoruz: filtreye hâlâ uyuyorsa seçim korunur, uymuyorsa düşer.
        chosen = self._selected_trip()
        self.trips = self._filtered()
        self.selected = self._index_of(chosen)
        self._fill_table()
        self._fill_kpis()
        self._fill_detail()
        self._dirty = set(range(len(charts.CHARTS)))
        self._draw_current()

        if not self.all_trips:
            self.status.config(text=t("status.empty"))
        elif not self.trips:
            self.status.config(text=t("status.no_match"))
        else:
            summary = stats.summarize(self.trips)
            first = i18n.date(summary.first_start) if summary.first_start else "—"
            last = i18n.date(summary.last_start) if summary.last_start else "—"
            self.status.config(text=t("status.showing", first=first, last=last, n=len(self.trips)))

    SORT_KEYS = {
        "start": lambda t: t.start_epoch,
        "duration": lambda t: t.duration_sec,
        "km": lambda t: t.distance_km,
        "consumption": lambda t: (t.consumption is None, t.consumption or 0.0),
        "energy": lambda t: (t.energy_kwh is None, t.energy_kwh or 0.0),
        "soc": lambda t: (t.soc_drop is None, t.soc_drop or 0.0),
        "speed": lambda t: (t.avg_speed_kmh is None, t.avg_speed_kmh or 0.0),
        "temp": lambda t: (t.temp is None, t.temp or 0.0),
    }

    def _sort_by(self, column: str) -> None:
        if column == self._sort_column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = True
        self._fill_table()

    def _index_of(self, trip: Trip | None) -> int | None:
        """Yolculuğun güncel listedeki sırası. Kimlikle arıyoruz: iki kayıt
        alan alan eşit olabilir, aradığımız o kayıt değil o nesne."""
        if trip is None:
            return None
        for index, candidate in enumerate(self.trips):
            if candidate is trip:
                return index
        return None

    def _selected_trip(self) -> Trip | None:
        if self.selected is None or not (0 <= self.selected < len(self.trips)):
            return None
        return self.trips[self.selected]

    def _fill_table(self) -> None:
        keep = self._selected_trip()
        self.tree.delete(*self.tree.get_children())

        key = self.SORT_KEYS.get(self._sort_column, self.SORT_KEYS["start"])
        order = sorted(enumerate(self.trips), key=lambda pair: key(pair[1]), reverse=self._sort_reverse)
        for row, (index, trip) in enumerate(order):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                tags=("odd",) if row % 2 else (),
                values=(
                    i18n.date_time(trip.start_dt),
                    trip.duration_text(),
                    num(trip.distance_km, 1),
                    num(trip.consumption, 1),
                    num(trip.energy_kwh, 2),
                    num(trip.soc_drop, 1),
                    num(trip.avg_speed_kmh, 0),
                    num(trip.temp, 0),
                ),
            )

        for column in self.SORT_KEYS:
            title = self.tree.heading(column)["text"].rstrip(" ▲▼")
            if column == self._sort_column:
                title += " ▼" if self._sort_reverse else " ▲"
            self.tree.heading(column, text=title)

        keep_index = self._index_of(keep)
        if keep_index is not None:
            iid = str(keep_index)
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def _fill_kpis(self) -> None:
        if not self.trips:
            for label in self.kpi_labels.values():
                label.config(text="—")
            return
        s = stats.summarize(self.trips)
        self.kpi_labels["trips"].config(text=str(s.trip_count))
        self.kpi_labels["km"].config(text=num(s.total_km, 1))
        self.kpi_labels["duration"].config(text=stats.duration_text(s.total_duration_sec))
        self.kpi_labels["consumption"].config(text=num(s.avg_consumption_kwh100, 1))
        self.kpi_labels["energy"].config(text=num(s.total_energy_kwh, 1))
        self.kpi_labels["regen"].config(text=num(s.total_regen_kwh, 1))
        self.kpi_labels["speed"].config(text=num(s.avg_speed_kmh, 0))
        self.kpi_labels["bias"].config(
            text=num(s.avg_range_bias, 2) if s.avg_range_bias is not None else "—"
        )

    # --- Seçim ve detay ------------------------------------------------------

    def _on_select(self, _event: object = None) -> None:
        selection = self.tree.selection()
        self.selected = int(selection[0]) if selection else None
        self._fill_detail()
        self._dirty = set(range(len(charts.CHARTS)))
        self._draw_current()

    def _fill_detail(self) -> None:
        self.detail_tree.delete(*self.detail_tree.get_children())
        # Yerel ad `trip`, `t` değil: `t` bu modülde çeviri fonksiyonu.
        trip = self._selected_trip()
        if trip is None:
            self.detail_title.config(text=t("detail.none"))
            self.detail_sub.config(text=t("detail.hint"))
            return

        speed = t("unit.speed")
        self.detail_title.config(text=i18n.date_time(trip.start_dt))
        self.detail_sub.config(
            text=t(
                "detail.sub",
                duration=trip.duration_text(),
                km=num(trip.distance_km, 1),
                end=i18n.clock(trip.end_dt),
                schema=trip.schema_version,
                source=trip.source or t("detail.no_source"),
            )
        )

        rows: list[tuple[str, str]] = [
            (t("detail.group.distance"), ""),
            (t("detail.gps_km"), f"{num(trip.distance_km, 2)} km"),
            (t("detail.wheel_km"), f"{num(trip.wheel_distance_km, 2)} km"),
            (t("detail.gps_wheel"), num(trip.gps_wheel_ratio, 3)),
            (t("detail.duration"), trip.duration_text()),
            (t("detail.group.energy"), ""),
            (t("detail.net"), f"{num(trip.energy_kwh, 3)} kWh"),
            (t("detail.regen"), f"{num(trip.regen_kwh, 3)} kWh"),
            (t("detail.gross"), f"{num(trip.gross_kwh, 3)} kWh"),
            (t("detail.regen_share"), i18n.pct(trip.regen_share)),
            (t("detail.consumption"), f"{num(trip.consumption, 2)} kWh/100 km"),
            (t("detail.potential"), f"{num(trip.potential_kwh, 3)} kWh"),
            (t("detail.group.battery"), ""),
            (t("detail.soc"), f"{i18n.pct(trip.soc_start, 1)} → {i18n.pct(trip.soc_end, 1)}"),
            (t("detail.soc_drop"), i18n.pct(trip.soc_drop, 1)),
            (t("detail.range"), f"{num(trip.range_start, 0)} → {num(trip.range_end, 0)} km"),
            (t("detail.range_drop"), f"{num(trip.range_drop, 0)} km"),
            (t("detail.bias"), stats.bias_verdict(trip.range_bias_factor)),
            (t("detail.group.speed"), ""),
            (t("detail.avg_speed"), f"{num(trip.avg_speed_kmh, 1)} {speed}"),
            (t("detail.max_speed"), f"{num(trip.max_speed_kmh, 1)} {speed}"),
            (t("detail.temp"), f"{num(trip.temp_start, 0)} / {num(trip.temp_avg, 1)} °C"),
            (t("detail.alt_gain"), f"{num(trip.alt_gain_m, 0)} m"),
            (t("detail.alt_loss"), f"{num(trip.alt_loss_m, 0)} m"),
            (t("detail.alt_net"), f"{num(trip.net_alt_m, 0)} m"),
        ]
        if trip.records:
            rows.append((t("detail.group.perf"), ""))
            for record in trip.records:
                rows.append((record.label, f"{record.pretty()} · {i18n.clock(record.when)}"))

        stripe = 0
        for field, value in rows:
            if not value:
                self.detail_tree.insert("", "end", values=(field, ""), tags=("group",))
                stripe = 0
                continue
            self.detail_tree.insert(
                "", "end", values=(field, value), tags=("odd",) if stripe % 2 else ()
            )
            stripe += 1

    # --- Çizim ---------------------------------------------------------------

    def _draw_current(self) -> None:
        index = self.tabs.index(self.tabs.select())
        if index >= len(charts.CHARTS):  # detay sekmesi
            return
        if index not in self._dirty:
            return
        figure = self._figures[index]
        figure.clear()
        try:
            charts.CHARTS[index][1](figure, self.trips, self.selected)
        except Exception as e:  # tek bir grafik hatası uygulamayı düşürmesin
            figure.clear()
            ax = figure.add_subplot(111)
            ax.set_axis_off()
            ax.text(0.5, 0.5, t("chart.failed", error=e), ha="center", va="center", color=theme.RED)
        self._canvases[index].draw_idle()
        self._dirty.discard(index)

    # --- Dışa aktarma --------------------------------------------------------

    def export_csv(self) -> None:
        if not self.trips:
            messagebox.showinfo(t("app.title"), t("export.nothing"))
            return
        path = filedialog.asksaveasfilename(
            title=t("export.csv_title"),
            defaultextension=".csv",
            initialfile=t("export.csv_filename"),
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return

        headers = [
            t("csv.start"), t("csv.end"), t("csv.duration"), t("csv.gps_km"),
            t("csv.wheel_km"), t("csv.net"), t("csv.regen"), t("csv.consumption"),
            t("csv.soc_start"), t("csv.soc_end"), t("csv.range_start"), t("csv.range_end"),
            t("csv.bias"), t("csv.avg_speed"), t("csv.max_speed"), t("csv.temp"),
            t("csv.alt_gain"), t("csv.alt_loss"), t("csv.potential"), t("csv.schema"),
            t("csv.source"),
        ]

        # Ayraç, ondalık ve tarih biçimi arayüz diline göre (i18n.csv_*): Türkçe
        # Excel ';' ve virgül, İngilizce Excel ',' ve nokta bekliyor.
        cell = i18n.csv_number
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.writer(fh, delimiter=i18n.csv_delimiter())
                writer.writerow(headers)
                for trip in sorted(self.trips, key=lambda x: x.start_epoch, reverse=True):
                    writer.writerow([
                        i18n.csv_datetime(trip.start_dt),
                        i18n.csv_datetime(trip.end_dt),
                        trip.duration_sec,
                        cell(trip.distance_km, 3),
                        cell(trip.wheel_distance_km, 3),
                        cell(trip.energy_kwh, 4),
                        cell(trip.regen_kwh, 4),
                        cell(trip.consumption, 2),
                        cell(trip.soc_start, 2),
                        cell(trip.soc_end, 2),
                        cell(trip.range_start, 0),
                        cell(trip.range_end, 0),
                        cell(trip.range_bias_factor, 3),
                        cell(trip.avg_speed_kmh, 2),
                        cell(trip.max_speed_kmh, 2),
                        cell(trip.temp_avg, 2),
                        cell(trip.alt_gain_m, 1),
                        cell(trip.alt_loss_m, 1),
                        cell(trip.potential_kwh, 4),
                        trip.schema_version,
                        trip.source,
                    ])
        except OSError as e:
            messagebox.showerror(t("app.title"), t("export.csv_failed", error=e))
            return
        self.status.config(text=t("status.csv_saved", path=path))

    def export_png(self) -> None:
        index = self.tabs.index(self.tabs.select())
        if index >= len(charts.CHARTS):
            messagebox.showinfo(t("app.title"), t("export.pick_chart"))
            return
        # Dosya adı sekmenin görünen adından: ex30-genel-bakış.png / ex30-overview.png
        name = t(charts.CHARTS[index][0]).lower().replace(" & ", "-").replace(" ", "-")
        path = filedialog.asksaveasfilename(
            title=t("export.png_title"),
            defaultextension=".png",
            initialfile=f"ex30-{name}.png",
            filetypes=[("PNG", "*.png")],
        )
        if not path:
            return
        self._figures[index].savefig(path, dpi=160, facecolor=theme.PANEL)
        self.status.config(text=t("status.png_saved", path=path))

    # --- Yardım --------------------------------------------------------------

    def show_help(self) -> None:
        messagebox.showinfo(t("app.title"), t("help.source"))

    def show_about(self) -> None:
        messagebox.showinfo(
            t("app.title"),
            t(
                "help.about",
                title=t("app.title"),
                python=sys.version.split()[0],
                mpl=matplotlib.__version__,
            ),
        )

def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    paths = [Path(a) for a in args if not a.startswith("-")]
    app = TripViewer(paths or None)
    app.mainloop()
    return 0
