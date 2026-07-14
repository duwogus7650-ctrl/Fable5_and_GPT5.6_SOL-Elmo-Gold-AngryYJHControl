"""Theme: QDD Anodized-Navy — ported from the SPG QDD Control Program (여재현).

Steel-navy motor-housing palette, cyan HUD corner brackets, monospace readouts.
Drop-in API-compatible with theme.py (same names, STYLE, HudCard).

2026-07-14 premium refinement: deeper layered grounds, a brighter instrument
cyan-blue accent, hairline sheen on panels, and glassier fields — a more
sophisticated anodized-aluminium instrument look (Qt QSS limits: no animation,
depth via gradients + drop-shadow effect).
"""
from PyQt6 import QtCore, QtGui, QtWidgets

THEME_NAME = "QDD Anodized-Navy"

# --- Premium anodized-navy palette (refined) ---
BG_TOP    = "#14294a"   # central gradient top — subtle steel glow
BG_MID    = "#0c1c30"
BG_BOT    = "#070f1c"   # deep base
SCROLL_BG = "#0a1727"
CARD      = "#0f1f36"   # panel
CARD_HI   = "#15294300"  # (reserved) panel top sheen anchor
CARD_SOFT = "#0a1728"   # inset / field ground
INSET     = "#08131f"
BORDER    = "#213f5e"   # hairline — defined but soft
BORDER_HI = "#2f527a"   # brighter hairline (hover/focus)
TEXT      = "#e9f1fc"
MUTED     = "#7f9bba"
FAINT     = "#4f6d8f"
SILVER    = "#b8cfe8"
INDIGO    = "#4bb6ee"   # PRIMARY ACCENT — instrument cyan-blue (brighter, premium)
VIOLET    = "#83d2f8"   # accent light
INDIGO_DK = "#2a6ea9"   # accent deep
ACCENT    = INDIGO
C_BLUE   = "#5aa8e6"
C_CORAL  = "#f2685a"
C_VIOLET = "#8ab6ff"
C_INDIGO = "#4bb6ee"
C_CYAN   = "#33e0d0"
C_AMBER  = "#f0aa3c"
C_GREEN  = "#33d38f"
C_TEAL   = "#2fd6c6"
MONO = '"JetBrains Mono","Cascadia Mono","Consolas","D2Coding",monospace'

GRAD_PRIMARY = (f"qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                f" stop:0 #57bdf2, stop:1 {INDIGO_DK})")
GRAD_STOP    = ("qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                " stop:0 #f4756a, stop:1 #c0342a)")
GRAD_OK      = ("qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                " stop:0 #37dd98, stop:1 #17a068)")

STYLE = f"""
* {{
    font-family: "Pretendard", "Segoe UI", "Malgun Gothic", sans-serif;
    font-size: 13px; color: {TEXT};
}}
QWidget#central {{
    background: qlineargradient(x1:0.1,y1:0,x2:0.55,y2:1,
        stop:0 {BG_TOP}, stop:0.5 {BG_MID}, stop:1 {BG_BOT});
}}

QFrame#card {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #142845, stop:0.06 #0f2038, stop:1 #0c1a2e);
    border: 1px solid {BORDER}; border-radius: 13px;
}}
QFrame#cell {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #0e1e34, stop:1 #0a1627);
    border: 1px solid #1d3a58; border-radius: 10px;
}}
QFrame#chip {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #132743, stop:1 #0e1d33);
    border: 1px solid {BORDER}; border-radius: 11px;
}}
QFrame#sep {{ background: {BORDER}; max-width: 1px; min-width: 1px; }}
QFrame#logochip {{ background: #eef4fc; border: 1px solid #9fbbdd; border-radius: 9px; }}

QLabel#brand {{ font-size: 22px; font-weight: 800; color: #f2f8ff; letter-spacing: 1px; }}
QLabel#brandsub {{ color: {INDIGO}; font-family: {MONO}; font-size: 12px; font-weight: 700; letter-spacing: 2px; }}
QLabel#madeby {{ color: {VIOLET}; font-family: {MONO}; font-size: 17px; font-weight: 800; letter-spacing: 2px; }}
QLabel[role="field"] {{ color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 0.6px; }}
QLabel[role="celltitle"] {{ color: {SILVER}; font-size: 12px; font-weight: 800; letter-spacing: 1.6px; }}
QLabel[role="hint"] {{ color: {FAINT}; font-size: 10px; font-weight: 600; }}
QLabel[role="metric_t"] {{ color: {MUTED}; font-family: {MONO}; font-size: 10px; font-weight: 700; letter-spacing: 1.6px; }}
QLabel[role="metric_v"] {{ font-family: {MONO}; font-size: 22px; font-weight: 800; letter-spacing: 0.5px; color: #dcecfd; }}
QLabel[role="fwval"] {{ color: {TEXT}; font-size: 12px; }}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {INSET}, stop:1 #061120);
    border: 1px solid #1e3a5a; border-radius: 8px;
    padding: 7px 12px; min-height: 18px; selection-background-color: {INDIGO}; selection-color: #06243a;
    color: #d8e9fb; font-weight: 600; font-family: {MONO};
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {BORDER_HI}; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {INDIGO}; color: {TEXT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ width: 0; height: 0; }}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; color: {TEXT};
    selection-background-color: {INDIGO}; selection-color: #06243a; outline: none; padding: 4px;
}}

QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #14294500, stop:0 #12243d, stop:1 #0d1c30);
    border: 1px solid {BORDER}; border-radius: 9px;
    padding: 8px 16px; color: {SILVER}; font-weight: 700;
}}
QPushButton:hover {{ border-color: {INDIGO}; color: {VIOLET}; }}
QPushButton:pressed {{ background: #0a1929; }}
QPushButton:disabled {{ color: #486788; border-color: #17324b; background: #0b1828; }}

QPushButton#primary {{
    background: {GRAD_PRIMARY}; border: 1px solid #62c2f5; color: #032334;
    font-weight: 800; padding: 9px 20px; border-radius: 9px;
}}
QPushButton#primary:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #6ecbff, stop:1 #3079b6); }}
QPushButton#primary:pressed {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #46a8e0, stop:1 #245f92); }}
QPushButton#primary:disabled {{ background: #0d1c30; border-color: #17324b; color: #486788; }}

QPushButton#stop {{
    background: {GRAD_STOP}; border: 1px solid #f4897e; color: #fff;
    font-size: 16px; font-weight: 900; letter-spacing: 3px; border-radius: 11px;
}}
QPushButton#stop:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f6564a, stop:1 #a82820); }}

QLabel#pill {{
    border-radius: 9px; padding: 6px 16px; font-family: {MONO}; font-weight: 800; font-size: 11px;
    letter-spacing: 1.6px; background: rgba(242,104,90,0.15); color: #ff8a7e;
    border: 1px solid rgba(242,104,90,0.5);
}}
QLabel#pill[on="true"] {{ background: {GRAD_OK}; color: #032a1c; border: 1px solid #4fe6a8; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {INDIGO}; padding: 5px 9px; border-radius: 6px; }}

QPlainTextEdit {{
    background: {INSET}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 10px; font-family: {MONO}; font-size: 12px;
    color: #bfe9f4; selection-background-color: {INDIGO}; selection-color: #06243a;
}}
QLabel#fwkey {{ color: {MUTED}; font-weight: 700; font-size: 12px; font-family: {MONO}; }}
QLabel#fwval {{ color: {TEXT}; font-weight: 600; font-size: 12px; }}

QCheckBox {{ color: {TEXT}; font-weight: 600; spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {BORDER}; background: {CARD_SOFT}; }}
QCheckBox::indicator:hover {{ border-color: {INDIGO}; }}
QCheckBox::indicator:checked {{ background: {INDIGO}; border: 1px solid {INDIGO}; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {INDIGO}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QStatusBar {{ color: {MUTED}; }}

QMessageBox, QDialog {{ background: {CARD}; }}
QMessageBox QLabel {{ color: {TEXT}; font-size: 13px; background: transparent; }}
QMessageBox QPushButton {{ min-width: 72px; padding: 7px 18px; }}
"""


def _shadow(widget, blur=34, dy=12, alpha=150):
    eff = QtWidgets.QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur); eff.setOffset(0, dy)
    eff.setColor(QtGui.QColor(1, 6, 12, alpha))
    widget.setGraphicsEffect(eff)


class HudCard(QtWidgets.QFrame):
    """Panel with translucent cyan HUD corner brackets + a hairline top sheen."""
    _BR = QtGui.QColor(95, 210, 248, 200)      # brighter cyan bracket
    _SHEEN = QtGui.QColor(120, 200, 255, 60)   # subtle top edge highlight

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        r = self.rect().adjusted(1, 1, -1, -1)
        # hairline top sheen (brushed-metal edge)
        grad = QtGui.QLinearGradient(r.left(), 0, r.right(), 0)
        grad.setColorAt(0.0, QtGui.QColor(120, 200, 255, 0))
        grad.setColorAt(0.5, self._SHEEN)
        grad.setColorAt(1.0, QtGui.QColor(120, 200, 255, 0))
        pen = QtGui.QPen(QtGui.QBrush(grad), 1.2)
        p.setPen(pen)
        p.drawLine(r.left() + 14, r.top() + 1, r.right() - 14, r.top() + 1)
        # cyan corner brackets
        pen = QtGui.QPen(self._BR); pen.setWidthF(1.7)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap); p.setPen(pen)
        m, L = 7, 15
        rr = self.rect().adjusted(m, m, -m, -m)
        x1, y1, x2, y2 = rr.left(), rr.top(), rr.right(), rr.bottom()
        for (cx, cy, dx, dy) in ((x1, y1, 1, 1), (x2, y1, -1, 1),
                                 (x1, y2, 1, -1), (x2, y2, -1, -1)):
            p.drawLine(cx, cy, cx + dx * L, cy)
            p.drawLine(cx, cy, cx, cy + dy * L)
        p.end()


__all__ = ['BG_TOP', 'BG_MID', 'BG_BOT', 'SCROLL_BG', 'CARD', 'CARD_HI', 'CARD_SOFT', 'INSET',
           'BORDER', 'BORDER_HI', 'TEXT', 'MUTED', 'FAINT', 'SILVER', 'INDIGO', 'VIOLET',
           'INDIGO_DK', 'ACCENT', 'C_BLUE', 'C_CORAL', 'C_VIOLET', 'C_INDIGO', 'C_CYAN',
           'C_AMBER', 'C_GREEN', 'C_TEAL', 'MONO', 'GRAD_PRIMARY', 'GRAD_STOP', 'GRAD_OK',
           'STYLE', '_shadow', 'HudCard', 'THEME_NAME']
