"""Темы оформления. Тема = палитра + декорации (снег, олени, шапки).

QSS строится из палитры, а виджеты, которые рисуют сами, берут цвета через C(key)
в момент отрисовки, поэтому смена темы применяется без перезапуска.
"""
from PyQt6.QtGui import QColor, QFont, QPalette

UI_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Arial"]
DISPLAY_FAMILIES = ["Segoe UI Variable Display", "Segoe UI", "Inter", "Arial"]

THEMES: dict[str, dict] = {
    "standard": {
        "title": "Тёмная", "description": "Спокойная тёмная", "dark": True,
        "snow": False, "reindeer": False, "hats": False,
        "bg": "#070707", "panel": "#121212", "surface": "#1a1a1a",
        "text": "#f2f2f2", "muted": "#8c8c8c", "help": "#b5b5b5", "error": "#ff8a80", "dim": "#5a5a5a",
        "scroll": "#2e2e2e", "scroll_hover": "#444444",
        "button": "#262626", "button_hover": "#313131", "focus": "#777777", "disabled": "#666666",
        "accent": "#f2f2f2", "accent_hover": "#ffffff", "on_accent": "#0d0d0d",
        "accent_disabled": "#9a9a9a",
        "input": "#101010", "input_border": "#2c2c2c", "selection": "#444444",
        "menu": "#1e1e1e", "menu_border": "#2c2c2c", "menu_sel": "#2c2c2c",
        "nav_hover": "#141414", "nav_checked": "#1c1c1c", "ctrl_hover": "#1c1c1c",
        "groove": "#2a2a2a", "placeholder": "#5f5f5f",
        "cover": "#232323", "cover_ring": "#3a3a3a",
        "wave_from": "#2b2b2b", "wave_to": "#121212", "wave_line": "#f2f2f2",
        "toggle_off": "#3a3a3a", "toggle_knob_off": "#d0d0d0",
    },
    "light": {
        "title": "Светлая", "description": "Светлая, для дня", "dark": False,
        "snow": False, "reindeer": False, "hats": False,
        "bg": "#e8e8eb", "panel": "#ffffff", "surface": "#f0f0f3",
        "text": "#141416", "muted": "#6b6b72", "help": "#4a4a50", "error": "#c62828", "dim": "#b3b3b8",
        "scroll": "#cfcfd5", "scroll_hover": "#b3b3ba",
        "button": "#e5e5ea", "button_hover": "#dadadf", "focus": "#8a8a92", "disabled": "#a0a0a6",
        "accent": "#141416", "accent_hover": "#000000", "on_accent": "#ffffff",
        "accent_disabled": "#9a9aa0",
        "input": "#ffffff", "input_border": "#d4d4da", "selection": "#cfd8ff",
        "menu": "#ffffff", "menu_border": "#d9d9df", "menu_sel": "#eeeef2",
        "nav_hover": "#dcdce1", "nav_checked": "#d2d2d8", "ctrl_hover": "#e3e3e8",
        "groove": "#d4d4da", "placeholder": "#9b9ba2",
        "cover": "#dcdce2", "cover_ring": "#c4c4cb",
        "wave_from": "#dcdce6", "wave_to": "#f6f6f8", "wave_line": "#2a2a30",
        "toggle_off": "#cfcfd5", "toggle_knob_off": "#ffffff",
    },
    "newyear": {
        "title": "Новогодняя", "description": "Красно-белая, со снегом и оленями", "dark": True,
        "snow": True, "reindeer": True, "hats": True,
        "bg": "#3d0710", "panel": "#5e0d18", "surface": "#741a25",
        "text": "#ffffff", "muted": "#f2c4c9", "help": "#f7d9dc", "error": "#ffd166", "dim": "#b5747c",
        "scroll": "#8a2c37", "scroll_hover": "#a8404b",
        "button": "#7e1f2a", "button_hover": "#93303b", "focus": "#ffffff", "disabled": "#c0868c",
        "accent": "#ffffff", "accent_hover": "#ffeef0", "on_accent": "#c8102e",
        "accent_disabled": "#d9a5ab",
        "input": "#4c0a13", "input_border": "#8a2c37", "selection": "#a8404b",
        "menu": "#5e0d18", "menu_border": "#8a2c37", "menu_sel": "#7e1f2a",
        "nav_hover": "#55101a", "nav_checked": "#6e1520", "ctrl_hover": "#55101a",
        "groove": "#8a2c37", "placeholder": "#d49aa1",
        "cover": "#7e1f2a", "cover_ring": "#9b3a45",
        "wave_from": "#b01e30", "wave_to": "#5e0d18", "wave_line": "#ffffff",
        "toggle_off": "#8a2c37", "toggle_knob_off": "#f2c4c9",
    },
}

_current_id = "standard"
_accent: str | None = None          # свой акцентный цвет поверх темы (None — как в теме)
_backgrounds: dict = {}             # свои цвета фона: {"sidebar": "#…", "panel": "#…"}
_palette: dict = {**THEMES["standard"], "side_text": THEMES["standard"]["text"],
                  "side_muted": THEMES["standard"]["muted"]}


def _with_accent(c: dict, accent: str | None) -> dict:
    if not accent:
        return dict(c)
    a = QColor(accent)
    out = dict(c)
    lum = 0.2126 * a.redF() + 0.7152 * a.greenF() + 0.0722 * a.blueF()
    out["accent"] = a.name()
    out["accent_hover"] = a.lighter(112).name()
    out["on_accent"] = "#111111" if lum > 0.55 else "#ffffff"   # иконка на кнопке читается всегда
    out["accent_disabled"] = QColor.fromHsvF(max(a.hsvHueF(), 0), a.hsvSaturationF() * 0.35,
                                             a.valueF() * 0.75).name()
    return out


def _lum(color: str) -> float:
    """Относительная яркость по WCAG."""
    c = QColor(color)

    def ch(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.redF()) + 0.7152 * ch(c.greenF()) + 0.0722 * ch(c.blueF())


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _shift(color: str, amount: float) -> str:
    """Чуть светлее на тёмном фоне и чуть темнее на светлом — для наведения, кнопок, полей."""
    c = QColor(color)
    h, s_, v = c.hsvHueF(), c.hsvSaturationF(), c.valueF()
    v = v + amount if _lum(color) < 0.35 else v - amount
    return QColor.fromHsvF(max(h, 0), s_, min(max(v, 0.0), 1.0)).name()


_TEXT = {True: ("#141416", "#5e5e66", "#3c3c42", "#a8a8ae", "#8e8e95"),     # на светлом фоне
         False: ("#f2f2f2", "#9a9aa2", "#c2c2c8", "#5c5c62", "#6a6a70")}    # на тёмном


def _with_backgrounds(c: dict, bg: dict) -> dict:
    out = dict(c)
    out.setdefault("side_text", out["text"])
    out.setdefault("side_muted", out["muted"])
    side = bg.get("sidebar")
    if side:
        out["bg"] = side
        out["nav_hover"], out["nav_checked"] = _shift(side, 0.05), _shift(side, 0.1)
        out["ctrl_hover"] = _shift(side, 0.07)
        if contrast(out["text"], side) < 4.5:   # текст меню и плеера читается всегда
            light = _lum(side) > 0.35
            out["side_text"], out["side_muted"] = _TEXT[light][0], _TEXT[light][1]
    panel = bg.get("panel")
    if panel:
        out["panel"] = panel
        out["surface"], out["button"], out["button_hover"] = (_shift(panel, 0.06), _shift(panel, 0.11),
                                                              _shift(panel, 0.16))
        out["input"], out["input_border"] = _shift(panel, -0.03), _shift(panel, 0.14)
        out["menu"], out["menu_border"], out["menu_sel"] = out["surface"], out["input_border"], out["button"]
        out["cover"], out["cover_ring"] = _shift(panel, 0.09), _shift(panel, 0.17)
        out["groove"], out["scroll"], out["scroll_hover"] = out["button"], out["button_hover"], _shift(panel, 0.22)
        out["toggle_off"] = out["button_hover"]
        out["wave_from"], out["wave_to"] = _shift(panel, 0.12), panel
        if contrast(out["text"], panel) < 4.5:   # светлый фон в тёмной теме (и наоборот) — меняем текст
            light = _lum(panel) > 0.35
            was_text = out["text"]
            out["text"], out["muted"], out["help"], out["dim"], out["placeholder"] = _TEXT[light]
            out["wave_line"] = out["text"]
            if out["accent"] == was_text:   # акцент «как текст» в стандартных темах — следом за текстом
                out["accent"] = out["text"]
                out["accent_hover"] = _shift(out["text"], 0.08)
                out["on_accent"] = "#ffffff" if light else "#111111"
    return out


def set_backgrounds(sidebar: str | None = None, panel: str | None = None) -> None:
    global _backgrounds
    _backgrounds = {k: v for k, v in (("sidebar", sidebar), ("panel", panel)) if v}


def set_accent(color: str | None) -> None:
    global _accent
    _accent = color


def C(key: str) -> str:
    """Цвет текущей темы (с учётом своего акцента)."""
    return _palette[key]


def current() -> dict:
    return _palette


def current_id() -> str:
    return _current_id


DARK_ID, LIGHT_ID, AUTO_ID, SPECIAL_IDS = "standard", "light", "auto", ("newyear",)
CHOICES = (DARK_ID, LIGHT_ID, AUTO_ID, *SPECIAL_IDS)   # варианты в настройках
DEFAULT_LIGHT_FROM, DEFAULT_DARK_FROM = "07:00", "20:00"


def _minutes(hhmm: str, fallback: str) -> int:
    try:
        h, m = (int(x) for x in hhmm.split(":"))
        return (h % 24) * 60 + m % 60
    except (ValueError, AttributeError):
        return _minutes(fallback, "00:00")


def is_light_time(light_from: str, dark_from: str, now=None) -> bool:
    """Светлая тема между light_from и dark_from; интервал может переходить через полночь."""
    import datetime
    now = now or datetime.datetime.now().time()
    t = now.hour * 60 + now.minute
    start = _minutes(light_from, DEFAULT_LIGHT_FROM)
    end = _minutes(dark_from, DEFAULT_DARK_FROM)
    if start == end:
        return True
    return start <= t < end if start < end else (t >= start or t < end)


def effective_theme(data: dict, now=None) -> str:
    """Какую тему показывать сейчас. «Авто» выбирает светлую или тёмную по времени;
    остальные варианты, включая новогоднюю, от времени не зависят."""
    chosen = data.get("theme", DARK_ID)
    if chosen != AUTO_ID:
        return chosen if chosen in THEMES else DARK_ID
    light = is_light_time(data.get("theme_light_from", DEFAULT_LIGHT_FROM),
                          data.get("theme_dark_from", DEFAULT_DARK_FROM), now)
    return LIGHT_ID if light else DARK_ID


def font(px: int, weight=QFont.Weight.Normal, display=False) -> QFont:
    f = QFont(DISPLAY_FAMILIES if display else UI_FAMILIES)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def build_qss(c: dict) -> str:
    return f"""
* {{ color: {c['text']}; }}
QMainWindow, #root, #sidebar {{ background: {c['bg']}; }}
#panel {{ background: transparent; }}
#playerBar {{ background: {c['bg']}; }}
#playerBar QLabel {{ color: {c['side_text']}; }}
#playerBar QLabel[role="muted"] {{ color: {c['side_muted']}; }}

QAbstractScrollArea {{ background: transparent; border: none; }}
QAbstractScrollArea > QWidget {{ background: transparent; }}
/* setWidget() включает содержимому автозаливку цветом окна: гасим, чтобы был виден фон темы */
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ width: 8px; background: transparent; margin: 4px 2px; }}
QScrollBar:horizontal {{ height: 8px; background: transparent; margin: 2px 4px; }}
QScrollBar::handle {{ background: {c['scroll']}; border-radius: 3px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {c['scroll_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0; }}

QLabel[role="muted"] {{ color: {c['muted']}; }}
QLabel[role="help"] {{ color: {c['help']}; }}
QLabel[role="error"] {{ color: {c['error']}; }}
QLabel[role="dim"] {{ color: {c['dim']}; }}

QFrame#card {{ background: transparent; border-radius: 14px; }}
QFrame#card:hover {{ background: {c['surface']}; }}
QFrame#groupHeader {{ background: transparent; border-radius: 10px; }}
QFrame#groupHeader:hover, QFrame#groupHeader:focus {{ background: {c['surface']}; }}
QFrame#emptyState {{ background: {c['surface']}; border-radius: 18px; }}
QFrame#serviceCard {{ background: {c['surface']}; border-radius: 14px; }}
QFrame#themeCard {{ background: {c['surface']}; border-radius: 16px; border: 2px solid transparent; }}
QFrame#themeCard:hover {{ border-color: {c['muted']}; }}
QFrame#themeCard[selected="true"] {{ border-color: {c['text']}; }}

QPushButton {{ background: {c['button']}; border: none; border-radius: 14px;
    padding: 9px 20px; font-weight: 600; }}
QPushButton:hover {{ background: {c['button_hover']}; }}
/* нажатие видно: кнопка темнеет и «проседает» на пиксель */
QPushButton:pressed {{ background: {c['nav_checked']}; padding-top: 10px; padding-bottom: 8px; }}
QPushButton:focus {{ outline: none; border: 1px solid {c['focus']}; }}
QPushButton:disabled {{ color: {c['disabled']}; }}
QPushButton#link {{ background: transparent; color: {c['muted']}; padding: 4px 0; font-weight: 600; }}
QPushButton#link:hover {{ color: {c['text']}; background: transparent; }}
QPushButton[compact="true"] {{ padding: 6px 14px; border-radius: 12px; font-size: 13px; }}
QPushButton[compact="true"]:pressed {{ padding-top: 7px; padding-bottom: 5px; }}
QPushButton#danger {{ color: {c['error']}; }}
QPushButton#danger:disabled {{ color: {c['disabled']}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {c['focus']};
    background: {c['input']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QPushButton[kind="primary"] {{ background: {c['accent']}; color: {c['on_accent']}; }}
QPushButton[kind="primary"]:hover {{ background: {c['accent_hover']}; }}
QPushButton[kind="primary"]:pressed {{ background: {c['accent_disabled']}; }}
QPushButton[kind="primary"]:disabled {{ background: {c['accent_disabled']}; color: {c['on_accent']}; }}

QTimeEdit {{ background: {c['input']}; border: 1px solid {c['input_border']}; border-radius: 10px;
    padding: 6px 10px; font-size: 14px; }}
QTimeEdit:focus {{ border-color: {c['focus']}; }}
QTimeEdit:disabled {{ color: {c['disabled']}; }}
QTimeEdit::up-button, QTimeEdit::down-button {{ width: 0; border: none; }}
QPlainTextEdit {{ background: {c['input']}; border: 1px solid {c['input_border']}; border-radius: 10px;
    padding: 6px 8px; selection-background-color: {c['selection']};
    font-family: Consolas, monospace; font-size: 12px; }}
QPlainTextEdit:focus {{ border-color: {c['focus']}; }}
QMenu {{ background: {c['menu']}; border: 1px solid {c['menu_border']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 8px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c['menu_sel']}; }}
QMenu::item:disabled {{ color: {c['disabled']}; }}
#videoWindow, QVideoWidget {{ background: #000; }}
#videoControls {{ background: {c['bg']}; }}
QLabel#videoStatus {{ background: #000; color: #9a9a9a; padding: 40px; }}
QLineEdit#search {{ background: {c['surface']}; border: 1px solid transparent; border-radius: 20px;
    padding: 9px 14px 9px 6px; font-size: 15px; }}
QLineEdit#search:focus {{ border-color: {c['focus']}; }}
QLineEdit {{ background: {c['input']}; border: 1px solid {c['input_border']}; border-radius: 10px;
    padding: 9px 12px; selection-background-color: {c['selection']}; }}
QLineEdit:focus {{ border-color: {c['focus']}; }}

QToolButton#nav {{ border: none; border-radius: 12px; }}
QToolButton#nav:hover {{ background: {c['nav_hover']}; }}
QToolButton#nav:checked {{ background: {c['nav_checked']}; }}
QToolButton#nav:pressed {{ background: {c['nav_checked']}; padding-top: 2px; }}
QToolButton#heroPlay {{ background: {c['accent']}; border: none; border-radius: 40px; }}
QToolButton#heroPlay:hover {{ background: {c['accent_hover']}; }}
QToolButton#ctrl {{ border: none; border-radius: 16px; }}
QToolButton#ctrl:hover {{ background: {c['ctrl_hover']}; }}
QToolButton#ctrl:pressed {{ background: {c['nav_checked']}; padding-top: 2px; }}
QToolButton#ctrl:disabled {{ background: transparent; }}
QToolButton#ctrl:checked {{ background: {c['nav_checked']}; }}
QToolButton#ctrlMain {{ background: {c['accent']}; border: none; border-radius: 20px; }}
QToolButton#ctrlMain:hover {{ background: {c['accent_hover']}; }}
QToolButton#ctrlMain:pressed {{ background: {c['accent_disabled']}; }}
QLineEdit#onboardName {{ background: rgba(255, 255, 255, 0.16); color: #ffffff;
    placeholder-text-color: rgba(255, 255, 255, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.35); border-radius: 16px; padding: 12px 16px; }}
QLineEdit#onboardName:focus {{ border-color: #ffffff; }}
QPushButton#onboardDone {{ background: #ffffff; color: #111111; border-radius: 16px;
    padding: 11px 20px; font-size: 16px; font-weight: 700; }}
QPushButton#onboardDone:hover {{ background: #f2f2f2; }}
QPushButton#onboardDone:disabled {{ background: rgba(255, 255, 255, 0.35); color: rgba(0, 0, 0, 0.45); }}
QPushButton#onboardSkip {{ background: transparent; color: rgba(255, 255, 255, 0.78); border: none;
    padding: 6px 12px; font-size: 14px; font-weight: 600; }}
QPushButton#onboardSkip:hover {{ color: #ffffff; background: transparent; }}
QToolButton#carouselArrow {{ background: rgba(255, 255, 255, 0.14); border: none; border-radius: 24px; }}
QToolButton#carouselArrow:hover {{ background: rgba(255, 255, 255, 0.26); }}
QToolButton#carouselArrow:pressed {{ background: rgba(255, 255, 255, 0.36); }}
QToolButton#profileBtn {{ border: none; border-radius: 24px; background: transparent; }}
QToolButton#profileBtn:hover {{ background: {c['nav_hover']}; }}
QFrame#flowPanel {{ background: {c['menu']}; border: 1px solid {c['menu_border']}; border-radius: 16px; }}
QToolButton#deviceRow {{ background: transparent; border: 1px solid transparent; border-radius: 12px;
    padding: 6px 10px; text-align: left; font-size: 13px; }}
QToolButton#deviceRow:hover {{ background: {c['menu_sel']}; }}
QToolButton#deviceRow:checked {{ background: {c['menu_sel']}; border-color: {c['text']}; font-weight: 600; }}
QToolButton#colorSwatch {{ border: 2px solid {c['menu_border']}; border-radius: 17px; background: transparent; }}
QToolButton#colorSwatch:hover {{ border-color: {c['text']}; }}
QToolButton#bigCtrl {{ border: none; background: transparent; border-radius: 12px; }}
QToolButton#bigCtrl:hover {{ background: rgba(255, 255, 255, 0.14); }}
QToolButton#bigCtrl:checked {{ background: rgba(255, 255, 255, 0.24); }}
QToolButton#bigPlay {{ background: {c['accent']}; border: none; border-radius: 38px; }}
QToolButton#bigPlay:hover {{ background: {c['accent_hover']}; }}
QSlider#bigSlider::groove:horizontal {{ height: 5px; background: rgba(255, 255, 255, 0.25); border-radius: 2px; }}
QSlider#bigSlider::sub-page:horizontal {{ background: #ffffff; border-radius: 2px; }}
QSlider#bigSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
    background: #ffffff; }}
QToolButton#artPlay {{ background: {c['accent']}; border: none; border-radius: 24px; }}
QToolButton#artPlay:hover {{ background: {c['accent_hover']}; }}
QToolButton#viewToggle {{ border: none; border-radius: 10px; padding: 4px; }}
QToolButton#viewToggle:hover {{ background: {c['surface']}; }}
QToolButton#viewToggle:checked {{ background: {c['button']}; }}
QToolButton#colorSwatch:checked {{ border-color: {c['text']}; }}
QToolButton#shelfArrow {{ background: {c['surface']}; border: none; border-radius: 16px; }}
QToolButton#shelfArrow:hover {{ background: {c['button_hover']}; }}
QToolButton#shelfArrow:disabled {{ background: transparent; }}
QPushButton#chip {{ background: {c['surface']}; border-radius: 13px; padding: 6px 14px; font-size: 13px; }}
QPushButton#chip:hover {{ background: {c['button_hover']}; }}
QPushButton#chip:checked {{ background: {c['accent']}; color: {c['on_accent']}; }}
QToolButton:focus {{ outline: none; }}

QSlider::groove:horizontal {{ height: 4px; background: {c['groove']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -4px 0;
    border-radius: 6px; background: {c['accent']}; }}

QTabWidget::pane {{ border: none; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 8px 0; margin-right: 26px;
    font-size: 15px; font-weight: 600; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom-color: {c['text']}; }}
QTabBar::tab:hover {{ color: {c['text']}; }}

QLabel#toast {{ background: {c['accent']}; color: {c['on_accent']}; border-radius: 12px;
    padding: 10px 18px; font-weight: 600; }}
QToolTip {{ background: {c['menu']}; color: {c['text']}; border: 1px solid {c['menu_border']};
    padding: 4px 8px; }}
"""


def apply_theme(app, theme_id: str = "standard") -> None:
    global _current_id, _palette
    _current_id = theme_id if theme_id in THEMES else "standard"
    c = _with_accent(_with_backgrounds(THEMES[_current_id], _backgrounds), _accent)
    _palette = c
    if (app.style().name() or "").lower() != "fusion":   # стиль ставится один раз: повтор стоил ~90 мс
        app.setStyle("Fusion")
    pal = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: c["panel"], QPalette.ColorRole.Base: c["input"],
        QPalette.ColorRole.AlternateBase: c["surface"], QPalette.ColorRole.Button: c["button"],
        QPalette.ColorRole.Text: c["text"], QPalette.ColorRole.WindowText: c["text"],
        QPalette.ColorRole.ButtonText: c["text"], QPalette.ColorRole.Highlight: c["selection"],
        QPalette.ColorRole.HighlightedText: c["text"], QPalette.ColorRole.ToolTipBase: c["menu"],
        QPalette.ColorRole.ToolTipText: c["text"], QPalette.ColorRole.PlaceholderText: c["placeholder"],
    }.items():
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setFont(font(14))
    qss = build_qss(c)
    if app.styleSheet() != qss:   # самое дорогое: Qt заново применяет стили ко всем виджетам
        app.setStyleSheet(qss)
