"""Grafik çizimleri. Her fonksiyon hazır bir Figure'a çizer, pencereyi tanımaz.

Ortak kurallar:

  * Veri yoksa eksen boş bırakılmaz, ortada sebebini söyleyen bir yazı olur.
    "Araç o property'yi vermedi" ile "değer sıfır" ayrı şeyler.
  * Eksik değer atlanır, sıfıra çevrilmez.
  * Seçili yolculuk her grafikte aynı biçimde vurgulanır.
  * Zaman ekseni yolculuk başlangıcına göredir; barlar sıra numarasına oturur,
    aralıklı tarihlerde bar genişliği yanıltıcı olmasın diye.
  * Metin, sayı ve tarih hep `i18n` üzerinden. Burada `t` adı çeviri için
    İÇE AKTARILMIYOR: fonksiyonların içinde `t` yolculuk değişkeni
    (`t = trips[selected]`) ve Python o fonksiyondaki bütün `t`'leri yerel
    sayıp çeviri çağrısını `UnboundLocalError` ile düşürürdü.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Callable, Sequence

import matplotlib
import matplotlib.dates as mdates
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize, TwoSlopeNorm
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import Formatter, MaxNLocator

from . import i18n, stats, theme
from .model import Trip
from .track import Track

#: Sekme adı → çizim fonksiyonu eşlemesi app.py tarafından kuruluyor.
ChartFn = Callable[[Figure, Sequence[Trip], int | None], None]


# --- Ortak yardımcılar -------------------------------------------------------


def _empty(fig: Figure, message: str) -> None:
    ax = fig.add_subplot(111)
    ax.set_axis_off()
    ax.text(
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        color=theme.MUTED,
        fontsize=11,
        wrap=True,
    )


def _no_data(ax, message: str) -> None:
    ax.set_axis_off()
    ax.text(0.5, 0.5, message, ha="center", va="center", color=theme.MUTED, fontsize=9)


def _time_kind(trips: Sequence[Trip]) -> str:
    """Kayıtların yayıldığı aralığa göre etiket türü (bkz. i18n.axis_label)."""
    if len(trips) < 2:
        return "daytime"
    # Yalnızca saat, ancak hepsi aynı takvim günündeyse: 2 günden kısa ama gece
    # yarısını aşan veride "11:23, 09:28" saat geri gidiyormuş gibi okunuyordu.
    if len({t.start_dt.date() for t in trips}) == 1:
        return "time"
    span_days = (trips[-1].start_dt - trips[0].start_dt).total_seconds() / 86400.0
    if span_days <= 2:
        return "daytime"
    if span_days <= 120:
        return "day"
    return "month"


#: Etiket yinelenirse geçilecek daha ayrıntılı tür. "daytime" en ayrıntılısı.
_MORE_DETAIL = {"month": "day", "day": "daytime", "time": "daytime"}


def _unique_labels(dts: Sequence[datetime], kind: str) -> list[str]:
    """Tarih etiketleri; yinelenen çıkarsa bütün eksen daha ayrıntılı türe geçer.

    Aynı gün yapılan iki yolculuk "12.09" etiketini paylaşıyordu: ayrı barlar
    aynı adı taşıyınca hangisinin hangisi olduğu okunamıyor. Saat eklenince
    ("12.09 09:28" / "12.09 09:34") ayrılıyorlar.
    """
    while True:
        labels = [i18n.axis_label(d, kind) for d in dts]
        if len(set(labels)) == len(labels) or kind not in _MORE_DETAIL:
            return labels
        kind = _MORE_DETAIL[kind]


def _tick_kind(dts: Sequence[datetime]) -> str:
    """Tiklerin GERÇEK aralığına göre etiket türü (bkz. i18n.axis_label).

    Tür verinin yayıldığı aralıktan seçilirse tiklerle tutmuyordu: matplotlib
    4,5 günlük veriye 12 saatte bir tik koyuyor, etiket yalnızca günü
    gösterdiği için her gün iki kez yazılıyordu; iki günlük veride tersi —
    tikler gün değiştiriyor, etiket yalnızca saati gösteriyordu. Tiklerden
    seçilince yakınlaştırmada da doğru kalıyor.
    """
    if len(dts) < 2:
        return "daytime"
    step_days = min((b - a).total_seconds() for a, b in zip(dts, dts[1:])) / 86400.0
    if step_days < 1.0:
        return "time" if len({d.date() for d in dts}) == 1 else "daytime"
    if step_days >= 28 and all(d.day == 1 for d in dts):
        return "month"
    return "day"


def _num2dt(x: float) -> datetime:
    # num2date UTC döndürüyor; çizilen saf yerel saatler de UTC sayıldığı için
    # tzinfo'yu atmak saati kaydırmıyor.
    return mdates.num2date(x).replace(tzinfo=None)


class _DateTickFormatter(Formatter):
    """Tarih ekseni biçimleyicisi: tiklere tek tek değil hep birlikte bakar.

    DateFormatter kullanılmıyor: strftime'a gidiyor ve ay adını işletim
    sisteminin yerel ayarından alıyor; etiketi dile göre i18n kuruyor.
    """

    def __call__(self, x: float, pos: int | None = None) -> str:
        # Tek değer yalnızca araç çubuğundaki imleç okumasında isteniyor.
        return i18n.axis_label(_num2dt(x), "daytime")

    def format_ticks(self, values: Sequence[float]) -> list[str]:
        self.set_locs(values)
        dts = [_num2dt(v) for v in values]
        return _unique_labels(dts, _tick_kind(dts))


def _index_axis(ax, trips: Sequence[Trip], max_labels: int = 14) -> None:
    """Sıra numarasına oturan barlar için tarih etiketleri."""
    n = len(trips)
    if n == 0:
        return
    step = max(1, math.ceil(n / max_labels))
    ticks = list(range(0, n, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels(
        _unique_labels([trips[i].start_dt for i in ticks], _time_kind(trips)),
        rotation=45,
        ha="right",
    )
    ax.set_xlim(-0.8, n - 0.2)


def _time_axis(ax) -> None:
    # En az 3 tik yeterli sayılıyor: varsayılan 5, 4 günlük veride 4 günlük
    # tiki az bulup saatlik aralığa iniyordu.
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=9))
    ax.xaxis.set_major_formatter(_DateTickFormatter())
    for label in ax.get_xticklabels():
        label.set_rotation(45)
        label.set_horizontalalignment("right")


def _mark_index(ax, index: int | None) -> None:
    if index is None:
        return
    ax.axvspan(index - 0.5, index + 0.5, color=theme.ACCENT, alpha=0.16, zorder=0)


def _mark_time(ax, when: datetime | None) -> None:
    if when is None:
        return
    ax.axvline(when, color=theme.ACCENT, alpha=0.45, linewidth=1.2, linestyle="--", zorder=0)


def _trend(ax, xs: Sequence[float], ys: Sequence[float], color: str) -> None:
    """Üç noktadan sonra eğilim doğrusu. Az veride çizgi uydurmak yanıltıcı."""
    if len(xs) < 3:
        return
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    if np.ptp(x) == 0:
        return
    slope, intercept = np.polyfit(x, y, 1)
    line_x = np.array([x.min(), x.max()])
    ax.plot(
        line_x,
        slope * line_x + intercept,
        color=color,
        linewidth=1.2,
        linestyle="--",
        alpha=0.8,
        zorder=1,
    )


def _pairs(trips: Sequence[Trip], fx, fy):
    """(x, y, trip) üçlüleri — iki değerden biri eksikse yolculuk atlanır."""
    out = []
    for t in trips:
        x = fx(t)
        y = fy(t)
        if x is None or y is None:
            continue
        out.append((x, y, t))
    return out


def _selected_dt(trips: Sequence[Trip], selected: int | None) -> datetime | None:
    if selected is None or not (0 <= selected < len(trips)):
        return None
    return trips[selected].start_dt


# --- 1. Genel bakış ----------------------------------------------------------


def draw_overview(fig: Figure, trips: Sequence[Trip], selected: int | None = None) -> None:
    if not trips:
        _empty(fig, i18n.t("chart.no_trips"))
        return

    gs = fig.add_gridspec(2, 2, height_ratios=(1.25, 1))
    ax_day = fig.add_subplot(gs[0, :])
    ax_band = fig.add_subplot(gs[1, 0])
    ax_hist = fig.add_subplot(gs[1, 1])

    # Günlük mesafe + kümülatif toplam
    days = stats.by_day(trips)
    ax_day.bar([d.day for d in days], [d.km for d in days], color=theme.ACCENT, width=0.7)
    ax_day.set_ylabel(i18n.t("chart.day.ylabel"))
    ax_day.set_title(i18n.t("chart.day.title"))

    ax_cum = ax_day.twinx()
    cumulative = np.cumsum([d.km for d in days])
    ax_cum.plot(
        [d.day for d in days],
        cumulative,
        color=theme.ORANGE,
        linewidth=1.8,
        marker="o",
        markersize=3,
    )
    ax_cum.set_ylabel(i18n.t("chart.day.cumulative"), color=theme.ORANGE)
    ax_cum.tick_params(axis="y", colors=theme.ORANGE)
    ax_cum.grid(False)
    _time_axis(ax_day)
    sel_dt = _selected_dt(trips, selected)
    if sel_dt is not None:
        ax_day.axvline(
            sel_dt.date(), color=theme.ACCENT, alpha=0.4, linestyle="--", linewidth=1.2, zorder=0
        )

    # Sıcaklık bandına göre ortalama tüketim (araçtaki Rekorlar ekranıyla aynı bantlar)
    bands = [b for b in stats.band_stats(trips) if b.trip_count > 0]
    measured = [b for b in bands if b.consumption_kwh100 is not None]
    if measured:
        labels = [b.label for b in measured]
        values = [b.consumption_kwh100 for b in measured]
        colors = [
            theme.BAND_COLORS[[s[0] for s in stats.BANDS].index(b.label)] for b in measured
        ]
        bars = ax_band.bar(labels, values, color=colors, width=0.6)
        ax_band.bar_label(
            bars, labels=[i18n.num(v, 1) for v in values], padding=2, color=theme.TEXT, fontsize=8
        )
        ax_band.set_ylabel("kWh/100 km")
        ax_band.set_title(i18n.t("chart.band.title"))
        ax_band.set_ylim(0, max(values) * 1.25)
        # Bandın altına o bandın toplam mesafesi: 14,1 kWh/100 km'nin kaç km
        # üzerinden ölçüldüğü görünmezse tek yolculukla yüz yolculuk eşit duruyor.
        ax_band.set_xticks(range(len(measured)))
        ax_band.set_xticklabels([f"{b.label}\n{i18n.num(b.km, 0)} km" for b in measured], fontsize=8)
    else:
        _no_data(ax_band, i18n.t("chart.band.none"))

    # Yolculuk uzunluğu dağılımı
    distances = [t.distance_km for t in trips if t.distance_km > 0]
    if distances:
        bins = min(20, max(5, int(math.sqrt(len(distances)) * 2)))
        ax_hist.hist(distances, bins=bins, color=theme.PURPLE, alpha=0.9)
        ax_hist.set_xlabel(i18n.t("chart.hist.xlabel"))
        ax_hist.set_ylabel(i18n.t("chart.hist.ylabel"))
        ax_hist.set_title(i18n.t("chart.hist.title"))
        # Sayım ekseni kesirli olamaz; az kayıtta 2,5 yolculuk yazıyordu.
        ax_hist.yaxis.set_major_locator(MaxNLocator(integer=True))
        median = float(np.median(distances))
        ax_hist.axvline(median, color=theme.ORANGE, linestyle="--", linewidth=1.2)
        ax_hist.legend(
            handles=[Line2D([], [], color=theme.ORANGE, linestyle="--", label=i18n.t("chart.hist.median", value=i18n.num(median, 1)))],
            loc="upper right",
        )
    else:
        _no_data(ax_hist, i18n.t("chart.hist.none"))


# --- 2. Tüketim --------------------------------------------------------------


def draw_consumption(fig: Figure, trips: Sequence[Trip], selected: int | None = None) -> None:
    data = [(t.start_dt, t.consumption, t) for t in trips if t.consumption is not None]
    if not data:
        _empty(fig, i18n.t("chart.cons.none"))
        return

    gs = fig.add_gridspec(2, 2, height_ratios=(1.2, 1))
    ax_time = fig.add_subplot(gs[0, :])
    ax_speed = fig.add_subplot(gs[1, 0])
    ax_temp = fig.add_subplot(gs[1, 1])

    xs = [d[0] for d in data]
    ys = [d[1] for d in data]
    sizes = [max(18.0, min(160.0, d[2].distance_km * 3.0)) for d in data]

    ax_time.plot(xs, ys, color=theme.ACCENT, linewidth=1.2, alpha=0.7, zorder=2)
    ax_time.scatter(xs, ys, s=sizes, color=theme.ACCENT, alpha=0.9, zorder=3, edgecolors="none")
    summary = stats.summarize(trips)
    if summary.avg_consumption_kwh100 is not None:
        ax_time.axhline(
            summary.avg_consumption_kwh100,
            color=theme.ORANGE,
            linestyle="--",
            linewidth=1.2,
            label=i18n.t("chart.cons.weighted", value=i18n.num(summary.avg_consumption_kwh100, 1)),
        )
        ax_time.legend(loc="best")
    ax_time.set_ylabel("kWh/100 km")
    ax_time.set_title(i18n.t("chart.cons.title"))
    _time_axis(ax_time)
    _mark_time(ax_time, _selected_dt(trips, selected))

    # Tüketim ↔ ortalama hız
    pairs = _pairs(trips, lambda t: t.avg_speed_kmh, lambda t: t.consumption)
    if pairs:
        px = [p[0] for p in pairs]
        py = [p[1] for p in pairs]
        ax_speed.scatter(px, py, s=40, color=theme.CYAN, alpha=0.9, edgecolors="none")
        _trend(ax_speed, px, py, theme.ORANGE)
        ax_speed.set_xlabel(i18n.t("chart.cons.speed.xlabel"))
        ax_speed.set_ylabel("kWh/100 km")
        ax_speed.set_title(i18n.t("chart.cons.speed.title"))
        if selected is not None and 0 <= selected < len(trips):
            t = trips[selected]
            if t.avg_speed_kmh is not None and t.consumption is not None:
                ax_speed.scatter(
                    [t.avg_speed_kmh],
                    [t.consumption],
                    s=150,
                    facecolors="none",
                    edgecolors=theme.TEXT,
                    linewidths=1.6,
                )
    else:
        _no_data(ax_speed, i18n.t("chart.no_speed"))

    # Tüketim ↔ dış sıcaklık
    pairs = _pairs(trips, lambda t: t.temp, lambda t: t.consumption)
    if pairs:
        px = [p[0] for p in pairs]
        py = [p[1] for p in pairs]
        ax_temp.scatter(px, py, s=40, color=theme.GREEN, alpha=0.9, edgecolors="none")
        _trend(ax_temp, px, py, theme.ORANGE)
        ax_temp.set_xlabel(i18n.t("chart.cons.temp.xlabel"))
        ax_temp.set_ylabel("kWh/100 km")
        ax_temp.set_title(i18n.t("chart.cons.temp.title"))
        if selected is not None and 0 <= selected < len(trips):
            t = trips[selected]
            if t.temp is not None and t.consumption is not None:
                ax_temp.scatter(
                    [t.temp],
                    [t.consumption],
                    s=150,
                    facecolors="none",
                    edgecolors=theme.TEXT,
                    linewidths=1.6,
                )
    else:
        _no_data(ax_temp, i18n.t("chart.no_temp"))


# --- 3. Enerji ve rejen ------------------------------------------------------


def draw_energy(fig: Figure, trips: Sequence[Trip], selected: int | None = None) -> None:
    measured = [t for t in trips if t.energy_kwh is not None]
    if not measured:
        _empty(fig, i18n.t("chart.energy.none"))
        return

    gs = fig.add_gridspec(2, 2, height_ratios=(1.2, 1))
    ax_bar = fig.add_subplot(gs[0, :])
    ax_share = fig.add_subplot(gs[1, 0])
    ax_alt = fig.add_subplot(gs[1, 1])

    # Net tüketim + rejen = brüt. energy_kwh NET olduğu için üst üste bindiriliyor.
    xs = np.arange(len(measured))
    net = np.array([t.energy_kwh for t in measured], dtype=float)
    regen = np.array([t.regen_kwh or 0.0 for t in measured], dtype=float)
    ax_bar.bar(xs, net, color=theme.ACCENT, width=0.7, label=i18n.t("chart.energy.net"))
    ax_bar.bar(xs, regen, bottom=net, color=theme.GREEN, width=0.7, label=i18n.t("chart.energy.regen"))
    ax_bar.set_ylabel("kWh")
    ax_bar.set_title(i18n.t("chart.energy.title"))
    ax_bar.legend(loc="upper left")
    _index_axis(ax_bar, measured)
    if selected is not None and 0 <= selected < len(trips):
        chosen = trips[selected]
        if chosen in measured:
            _mark_index(ax_bar, measured.index(chosen))

    # Rejen payı
    shares = [(i, t.regen_share) for i, t in enumerate(measured) if t.regen_share is not None]
    if shares:
        idx = [s[0] for s in shares]
        vals = [s[1] for s in shares]
        ax_share.bar(idx, vals, color=theme.GREEN, width=0.7)
        mean_share = float(np.mean(vals))
        ax_share.axhline(
            mean_share,
            color=theme.ORANGE,
            linestyle="--",
            linewidth=1.2,
            label=i18n.t("chart.average", value=i18n.pct(mean_share)),
        )
        ax_share.legend(loc="best")
        ax_share.set_ylabel(i18n.t("chart.share.ylabel"))
        ax_share.set_title(i18n.t("chart.share.title"))
        _index_axis(ax_share, measured, max_labels=8)
    else:
        _no_data(ax_share, i18n.t("chart.share.none"))

    # Rejen ↔ toplam iniş: inişin ne kadarı geri geliyor
    pairs = _pairs(trips, lambda t: t.alt_loss_m if t.alt_loss_m > 0 else None, lambda t: t.regen_kwh)
    if pairs:
        px = [p[0] for p in pairs]
        py = [p[1] for p in pairs]
        ax_alt.scatter(px, py, s=40, color=theme.PURPLE, alpha=0.9, edgecolors="none")
        _trend(ax_alt, px, py, theme.ORANGE)
        ax_alt.set_xlabel(i18n.t("chart.descent.xlabel"))
        ax_alt.set_ylabel(i18n.t("chart.descent.ylabel"))
        ax_alt.set_title(i18n.t("chart.descent.title"))
    else:
        _no_data(ax_alt, i18n.t("chart.descent.none"))


# --- 4. Batarya ve menzil ----------------------------------------------------


def draw_battery(fig: Figure, trips: Sequence[Trip], selected: int | None = None) -> None:
    soc = [t for t in trips if t.soc_start is not None and t.soc_end is not None]
    bias = [t for t in trips if t.range_bias_factor is not None]
    if not soc and not bias:
        _empty(fig, i18n.t("chart.battery.none"))
        return

    gs = fig.add_gridspec(2, 2, height_ratios=(1.2, 1))
    ax_soc = fig.add_subplot(gs[0, :])
    ax_bias = fig.add_subplot(gs[1, 0])
    ax_range = fig.add_subplot(gs[1, 1])

    if soc:
        xs = [t.start_dt for t in soc]
        starts = [t.soc_start for t in soc]
        ends = [t.soc_end for t in soc]
        ax_soc.vlines(xs, ends, starts, color=theme.LINE, linewidth=3)
        ax_soc.scatter(xs, starts, s=28, color=theme.ACCENT, zorder=3, label=i18n.t("chart.soc.start"))
        ax_soc.scatter(xs, ends, s=28, color=theme.RED, zorder=3, label=i18n.t("chart.soc.end"))
        ax_soc.set_ylabel("SoC (%)")
        ax_soc.set_title(i18n.t("chart.soc.title"))
        ax_soc.set_ylim(0, 100)
        ax_soc.legend(loc="best")
        _time_axis(ax_soc)
        _mark_time(ax_soc, _selected_dt(trips, selected))
    else:
        _no_data(ax_soc, i18n.t("chart.soc.none"))

    # Menzil sapması: 1,0 = gösterge tuttu
    if bias:
        idx = np.arange(len(bias))
        values = [t.range_bias_factor for t in bias]
        colors = [
            theme.GREEN if abs(v - 1.0) <= stats.ACCURATE_BAND else (theme.RED if v > 1 else theme.CYAN)
            for v in values
        ]
        ax_bias.scatter(idx, values, s=45, color=colors, edgecolors="none", zorder=3)
        ax_bias.axhspan(
            1 - stats.ACCURATE_BAND, 1 + stats.ACCURATE_BAND, color=theme.GREEN, alpha=0.12, zorder=0
        )
        ax_bias.axhline(1.0, color=theme.MUTED, linewidth=1)
        avg = stats.average_range_bias(trips)
        if avg is not None:
            ax_bias.axhline(
                avg, color=theme.ORANGE, linestyle="--", linewidth=1.2, label=i18n.t("chart.average", value=i18n.num(avg, 2))
            )
            ax_bias.legend(loc="lower right")
        ax_bias.set_ylabel(i18n.t("chart.bias.ylabel"))
        ax_bias.set_title(i18n.t("chart.bias.title"))
        ax_bias.text(
            0.01,
            0.97,
            i18n.t("chart.bias.note"),
            transform=ax_bias.transAxes,
            va="top",
            fontsize=7.5,
            color=theme.MUTED,
            # Zemin olmadan yazı noktaların üstüne biniyor ve ikisi de okunmuyor.
            bbox=dict(facecolor=theme.PANEL, edgecolor="none", alpha=0.85, pad=2),
        )
        _index_axis(ax_bias, bias, max_labels=8)
    else:
        _no_data(
            ax_bias,
            i18n.t("chart.bias.none", km=i18n.num(stats.MIN_BIAS_DISTANCE_KM, 0)),
        )

    # Gösterge menzil düşüşü ↔ gerçekte gidilen mesafe
    pairs = _pairs(trips, lambda t: t.distance_km or None, lambda t: t.range_drop)
    if pairs:
        px = [p[0] for p in pairs]
        py = [p[1] for p in pairs]
        limit = max(max(px), max(py)) * 1.08
        ax_range.plot([0, limit], [0, limit], color=theme.MUTED, linewidth=1, linestyle="--")
        ax_range.scatter(px, py, s=40, color=theme.PURPLE, alpha=0.9, edgecolors="none")
        ax_range.set_xlim(0, limit)
        ax_range.set_ylim(0, limit)
        ax_range.set_xlabel(i18n.t("chart.range.xlabel"))
        ax_range.set_ylabel(i18n.t("chart.range.ylabel"))
        ax_range.set_title(i18n.t("chart.range.title"))
    else:
        _no_data(ax_range, i18n.t("chart.range.none"))


# --- 5. Hız ve rakım ---------------------------------------------------------


def draw_speed(fig: Figure, trips: Sequence[Trip], selected: int | None = None) -> None:
    speeds = [t for t in trips if t.avg_speed_kmh is not None or t.max_speed_kmh is not None]
    if not trips:
        _empty(fig, i18n.t("chart.no_trips"))
        return

    gs = fig.add_gridspec(2, 2, height_ratios=(1.2, 1))
    ax_speed = fig.add_subplot(gs[0, :])
    ax_alt = fig.add_subplot(gs[1, 0])
    ax_ratio = fig.add_subplot(gs[1, 1])

    if speeds:
        idx = np.arange(len(speeds))
        avg = [t.avg_speed_kmh for t in speeds]
        top = [t.max_speed_kmh for t in speeds]
        for i, t in enumerate(speeds):
            if t.avg_speed_kmh is not None and t.max_speed_kmh is not None:
                ax_speed.vlines(i, t.avg_speed_kmh, t.max_speed_kmh, color=theme.LINE, linewidth=2.5)
        ax_speed.scatter(
            [i for i, v in enumerate(avg) if v is not None],
            [v for v in avg if v is not None],
            s=32,
            color=theme.ACCENT,
            zorder=3,
            label=i18n.t("chart.speed.average"),
        )
        ax_speed.scatter(
            [i for i, v in enumerate(top) if v is not None],
            [v for v in top if v is not None],
            s=32,
            color=theme.ORANGE,
            zorder=3,
            label=i18n.t("chart.speed.top"),
        )
        ax_speed.set_ylabel(i18n.t("unit.speed"))
        ax_speed.set_title(i18n.t("chart.speed.title"))
        ax_speed.legend(loc="best")
        _index_axis(ax_speed, speeds)
        if selected is not None and 0 <= selected < len(trips) and trips[selected] in speeds:
            _mark_index(ax_speed, speeds.index(trips[selected]))
    else:
        _no_data(ax_speed, i18n.t("chart.no_speed"))

    # Rakım kazancı / kaybı — sıfırın iki yanında
    climbs = [t for t in trips if t.alt_gain_m > 0 or t.alt_loss_m > 0]
    if climbs:
        idx = np.arange(len(climbs))
        gain = [t.alt_gain_m for t in climbs]
        loss = [-t.alt_loss_m for t in climbs]
        ax_alt.bar(idx, gain, color=theme.GREEN, width=0.7, label=i18n.t("chart.alt.climb"))
        ax_alt.bar(idx, loss, color=theme.RED, width=0.7, label=i18n.t("chart.alt.descent"))
        ax_alt.axhline(0, color=theme.MUTED, linewidth=1)
        ax_alt.set_ylabel(i18n.t("chart.alt.ylabel"))
        ax_alt.set_title(i18n.t("chart.alt.title"))
        ax_alt.legend(loc="best")
        _index_axis(ax_alt, climbs, max_labels=8)
    else:
        _no_data(ax_alt, i18n.t("chart.alt.none"))

    # GPS ↔ tekerlek mesafesi (şema 3): GPS'in hatasını gösteren tek ölçü
    ratios = [(i, t.gps_wheel_ratio) for i, t in enumerate(trips) if t.gps_wheel_ratio is not None]
    if ratios:
        ax_ratio.axhline(1.0, color=theme.MUTED, linewidth=1)
        ax_ratio.scatter(
            [r[0] for r in ratios],
            [r[1] for r in ratios],
            s=40,
            color=theme.CYAN,
            edgecolors="none",
        )
        mean_ratio = float(np.mean([r[1] for r in ratios]))
        ax_ratio.axhline(
            mean_ratio,
            color=theme.ORANGE,
            linestyle="--",
            linewidth=1.2,
            label=i18n.t("chart.average", value=i18n.num(mean_ratio, 3)),
        )
        ax_ratio.legend(loc="best")
        ax_ratio.set_ylabel(i18n.t("chart.ratio.ylabel"))
        ax_ratio.set_title(i18n.t("chart.ratio.title"))
        _index_axis(ax_ratio, trips, max_labels=8)
    else:
        _no_data(ax_ratio, i18n.t("chart.ratio.none"))


#: Sekme sırası — app.py bu listeden kuruyor. İlk alan sekme adının dil anahtarı.
CHARTS: tuple[tuple[str, ChartFn], ...] = (
    ("tab.overview", draw_overview),
    ("tab.consumption", draw_consumption),
    ("tab.energy", draw_energy),
    ("tab.battery", draw_battery),
    ("tab.speed", draw_speed),
)


# --- Rota (seçili yolculuğun GPS izi) -------------------------------------------
# Yolculuk listesiyle değil tek bir izle çalıştığı için CHARTS'ta değil; sekmesini
# app.py ayrıca kuruyor. Harita karosu YOK: yalnızca matplotlib, yeni bağımlılık
# ve ağ isteği olmasın. En-boy oranı enleme göre düzeltiliyor ki rota basık
# görünmesin.

#: Rota çizgisinin renklendirme seçenekleri (lang: route.color.<ad>).
ROUTE_COLORS: tuple[str, ...] = ("speed", "power", "alt")

#: İrtifa profilindeki kayan ortalamanın genişliği (nokta). İz ~1 Hz; ham GPS
#: irtifası metrelerce zıplıyor, 15 s'lik pencere eğimi bozmadan yumuşatıyor.
ALT_SMOOTH_POINTS = 15

#: Güç renk skalası: rejen (negatif) yeşil, sıfır nötr gri, tüketim turuncu→kırmızı.
#: Nötr ton zeminden açık: sabit hızda süzülen parça koyu zeminde kaybolmasın.
POWER_CMAP = LinearSegmentedColormap.from_list(
    "ex30_power", [theme.GREEN, theme.MUTED, theme.ORANGE, theme.RED]
)

#: Rota çizgisinde değeri olmayan parçanın rengi — skaladaki hiçbir tonla
#: karışmasın diye zeminle nötr gri arası.
ROUTE_MISSING = "#566070"


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    """NaN'ı atlayan ortalanmış kayan ortalama. Eksik nokta sıfır sayılsaydı
    profilde sahte çukurlar çıkardı."""
    ok = np.isfinite(values)
    # `convolve(..., "same")` pencereden kısa dizide pencere boyunda sonuç
    # veriyor; birkaç noktalık izde pencere izin kendisine iniyor.
    window = min(window, values.size)
    if window <= 1 or not ok.any():
        return values.copy()
    kernel = np.ones(window)
    total = np.convolve(np.where(ok, values, 0.0), kernel, mode="same")
    count = np.convolve(ok.astype(float), kernel, mode="same")
    with np.errstate(invalid="ignore", divide="ignore"):
        out = total / count
    out[~ok] = np.nan
    return out


def _route_scale(color_by: str, values: np.ndarray):
    """(renk haritası, normalleştirme, etiket) — renklendirilecek değer yoksa None."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    lo, hi = float(finite.min()), float(finite.max())
    if color_by == "power":
        # İki yönlü: sıfır her zaman ortada. Yalnızca tüketim ya da yalnızca
        # rejen olan izde de TwoSlopeNorm'un iki yanı boş kalmasın.
        norm = TwoSlopeNorm(vcenter=0.0, vmin=min(lo, -1.0), vmax=max(hi, 1.0))
        cmap = POWER_CMAP.copy()
        label = i18n.t("route.power.label")
    elif color_by == "alt":
        norm = Normalize(lo, hi if hi > lo else lo + 1.0)
        cmap = matplotlib.colormaps["viridis"].copy()
        label = i18n.t("route.alt.label")
    else:
        norm = Normalize(0.0, hi if hi > 0 else 1.0)
        cmap = matplotlib.colormaps["plasma"].copy()
        label = i18n.t("route.speed.label")
    # Değeri olmayan parça sönük çiziliyor, atlanmıyor: rota kopuk görünmesin.
    cmap.set_bad(ROUTE_MISSING)
    return cmap, norm, label


def _shade_regen(ax, x: np.ndarray, kw: np.ndarray) -> None:
    """Rejen bölgelerini (kw < 0) eksenin bütün yüksekliğinde hafifçe boyar."""
    regen = np.isfinite(kw) & (kw < 0)
    if not regen.any():
        return
    ax.fill_between(
        x,
        0,
        1,
        where=regen,
        transform=ax.get_xaxis_transform(),
        color=theme.GREEN,
        alpha=0.12,
        linewidth=0,
        step="mid",
        zorder=0,
        label=i18n.t("route.power.regen"),
    )


def _note(ax, text: str) -> None:
    ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center",
            color=theme.MUTED, fontsize=9)


def draw_route(
    fig: Figure,
    track: Track | None,
    color_by: str = "speed",
    message: str | None = None,
) -> None:
    """Seçili yolculuğun rotası + mesafe eksenli irtifa, hız ve güç profilleri.

    Profillerin x ekseni bağlı (`sharex`): biri yakınlaştırılınca üçü birden
    gelir, haritada da o aralık vurgulanır. `message`: iz yoksa ortada
    gösterilecek sebep (iz yok, indiriliyor, hata…).
    """
    if track is None:
        _empty(fig, message or i18n.t("route.none"))
        return
    if track.rows == 0:
        _empty(fig, i18n.t("route.empty"))
        return

    x = track.distance_m() / 1000.0
    lat, lon = track.array("lat"), track.array("lon")
    alt = track.array("alt")
    speed = track.speed_kmh()
    kw = track.array("kw")

    gs = fig.add_gridspec(3, 2, width_ratios=(1.1, 1))
    ax_map = fig.add_subplot(gs[:, 0])
    ax_alt = fig.add_subplot(gs[0, 1])
    ax_speed = fig.add_subplot(gs[1, 1], sharex=ax_alt)
    ax_kw = fig.add_subplot(gs[2, 1], sharex=ax_alt)

    has_x = bool(np.isfinite(x).any())
    fig.suptitle(
        i18n.t(
            "route.title",
            when=i18n.date_time(track.start_dt),
            km=i18n.num(float(np.nanmax(x)) if has_x else None, 1),
            points=i18n.num(track.rows, 0),
        ),
        color=theme.TEXT,
        fontsize=11,
    )

    # --- Harita ---------------------------------------------------------------
    have = np.isfinite(lat) & np.isfinite(lon)
    highlight = None
    if have.sum() >= 2:
        values = {"power": kw, "alt": alt}.get(color_by, speed)
        px, py, pv = lon[have], lat[have], values[have]
        segments = np.stack(
            [np.column_stack([px[:-1], py[:-1]]), np.column_stack([px[1:], py[1:]])], axis=1
        )
        scale = _route_scale(color_by, pv)
        if scale is not None:
            cmap, norm, label = scale
            lines = LineCollection(segments, cmap=cmap, norm=norm, linewidths=2.4, capstyle="round")
            lines.set_array(np.ma.masked_invalid(pv[:-1]))
            ax_map.add_collection(lines)
            bar = fig.colorbar(lines, ax=ax_map, shrink=0.6, pad=0.02)
            bar.set_label(label)
            bar.outline.set_edgecolor(theme.LINE)
        else:
            ax_map.add_collection(LineCollection(segments, colors=theme.ACCENT, linewidths=2.4))
            ax_map.text(0.01, 0.99, i18n.t("route.no_color"), transform=ax_map.transAxes,
                        va="top", fontsize=8, color=theme.MUTED)
        ax_map.scatter([px[0]], [py[0]], s=60, color=theme.GREEN, edgecolors=theme.TEXT,
                       zorder=4, label=i18n.t("route.start"))
        ax_map.scatter([px[-1]], [py[-1]], s=60, marker="s", color=theme.RED,
                       edgecolors=theme.TEXT, zorder=4, label=i18n.t("route.end"))
        ax_map.legend(loc="lower right")
        ax_map.autoscale_view()
        # Boylamın bir derecesi enlemin cos'u kadar kısa: düzeltilmezse
        # İstanbul'da doğu-batı yolları %30 uzun görünür.
        mean_lat = float(np.mean(py))
        ax_map.set_aspect(1.0 / max(math.cos(math.radians(mean_lat)), 0.01), adjustable="datalim")
        ax_map.set_xlabel(i18n.t("route.lon"))
        ax_map.set_ylabel(i18n.t("route.lat"))
        ax_map.set_title(i18n.t("route.map.title"))
        ax_map.ticklabel_format(useOffset=False)
        highlight = ax_map.plot([], [], color=theme.TEXT, linewidth=7, alpha=0.45, zorder=1,
                                solid_capstyle="round")[0]
    else:
        _no_data(ax_map, i18n.t("route.no_position"))

    # --- İrtifa profili ---------------------------------------------------------
    if np.isfinite(alt).any():
        ax_alt.plot(x, alt, color=theme.MUTED, linewidth=0.8, alpha=0.7,
                    label=i18n.t("route.alt.raw"))
        ax_alt.plot(x, _smooth(alt, ALT_SMOOTH_POINTS), color=theme.PURPLE, linewidth=1.8,
                    label=i18n.t("route.alt.smooth", n=ALT_SMOOTH_POINTS))
        ax_alt.legend(loc="best")
        ax_alt.set_ylabel(i18n.t("route.alt.ylabel"))
    else:
        _note(ax_alt, i18n.t("route.alt.none"))
    ax_alt.set_title(i18n.t("route.alt.title"))

    # --- Hız ------------------------------------------------------------------
    if np.isfinite(speed).any():
        _shade_regen(ax_speed, x, kw)
        ax_speed.plot(x, speed, color=theme.ACCENT, linewidth=1.3, label=i18n.t("route.speed.car"))
        if track.has("kmh") and track.has("gps_kmh"):
            ax_speed.plot(x, track.array("gps_kmh"), color=theme.CYAN, linewidth=0.8, alpha=0.6,
                          label=i18n.t("route.speed.gps"))
        ax_speed.legend(loc="best")
        ax_speed.set_ylabel(i18n.t("unit.speed"))
    else:
        _note(ax_speed, i18n.t("chart.no_speed"))
    ax_speed.set_title(i18n.t("route.speed.title"))

    # --- Güç: pozitif tüketim, negatif rejen --------------------------------------
    if np.isfinite(kw).any():
        use = np.where(np.isfinite(kw) & (kw >= 0), kw, np.nan)
        regen = np.where(np.isfinite(kw) & (kw < 0), kw, np.nan)
        ax_kw.fill_between(x, np.nan_to_num(use), 0, where=np.isfinite(use), color=theme.ORANGE,
                           alpha=0.45, linewidth=0, step="mid", label=i18n.t("route.power.use"))
        ax_kw.fill_between(x, np.nan_to_num(regen), 0, where=np.isfinite(regen), color=theme.GREEN,
                           alpha=0.6, linewidth=0, step="mid", label=i18n.t("route.power.regen"))
        ax_kw.plot(x, kw, color=theme.TEXT, linewidth=0.6, alpha=0.6)
        ax_kw.axhline(0, color=theme.MUTED, linewidth=0.8)
        ax_kw.legend(loc="best")
        ax_kw.set_ylabel(i18n.t("route.power.ylabel"))
    else:
        _note(ax_kw, i18n.t("route.power.none"))
    ax_kw.set_title(i18n.t("route.power.title"))
    ax_kw.set_xlabel(i18n.t("route.distance"))
    for ax in (ax_alt, ax_speed):
        ax.tick_params(labelbottom=False)

    if has_x:
        full = (float(np.nanmin(x)), float(np.nanmax(x)))
        if full[1] > full[0]:
            ax_alt.set_xlim(*full)
        if highlight is not None:
            _link_highlight(ax_alt, highlight, x, lon, lat, full)


def _link_highlight(ax, line: Line2D, x: np.ndarray, lon: np.ndarray, lat: np.ndarray,
                    full: tuple[float, float]) -> None:
    """Profiller yakınlaştırılınca haritada o mesafe aralığını vurgular.

    Tkinter'a değil matplotlib'in kendi olayına bağlı (`xlim_changed`): araç
    çubuğunun yakınlaştırması da, koddan `set_xlim` de aynı yolu izliyor. Tam
    aralıkta vurgu kalkıyor — bütün rotayı kalın bir çizgiyle örtmesin.
    """
    span = full[1] - full[0]

    def update(axis) -> None:
        lo, hi = axis.get_xlim()
        if span <= 0 or (lo <= full[0] + span * 0.001 and hi >= full[1] - span * 0.001):
            line.set_data([], [])
            return
        inside = np.isfinite(x) & (x >= lo) & (x <= hi) & np.isfinite(lon) & np.isfinite(lat)
        line.set_data(lon[inside], lat[inside])

    ax.callbacks.connect("xlim_changed", update)
