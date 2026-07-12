"""Theme: QDD Anodized-Navy — ported from the SPG QDD Control Program (여재현).

Steel-navy motor-housing palette, cyan HUD corner brackets, monospace readouts.
Drop-in API-compatible with theme.py (same names, STYLE, HudCard).
"""
from PyQt6 import QtCore, QtGui, QtWidgets

THEME_NAME = "QDD Anodized-Navy"

# --- Anodized-navy palette (matched to the SPG QDD motor housing) ---
BG_TOP    = "#0e2038"
BG_BOT    = "#0a1522"
SCROLL_BG = "#0c1d30"
CARD      = "#1a2c44"
CARD_SOFT = "#12233a"
BORDER    = "#2c4a70"
TEXT      = "#e8f1fb"
MUTED     = "#8aa4c0"
SILVER    = "#c3ccd6"
INDIGO    = "#4a72b8"
VIOLET    = "#5a86c8"
INDIGO_DK = "#3f63a0"
ACCENT    = INDIGO
C_BLUE   = "#5a86c8"
C_CORAL  = "#ff6b8a"
C_VIOLET = "#8aa6ff"
C_INDIGO = "#4a72b8"
C_CYAN   = "#26e0cf"
C_AMBER  = "#ffb648"
C_GREEN  = "#3ce0a3"
C_TEAL   = "#2fd6c6"
MONO = '"JetBrains Mono","Consolas","Cascadia Mono","D2Coding",monospace'
GRAD_PRIMARY = f"qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {INDIGO}, stop:1 {VIOLET})"
GRAD_STOP    = "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ff5c7a, stop:1 #e11d48)"
GRAD_OK      = "qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #3ce0a3, stop:1 #10b981)"

STYLE = f"""
* {{
    font-family: "Pretendard", "Segoe UI", "Malgun Gothic", sans-serif;
    font-size: 13px; color: {TEXT};
}}
QWidget#central {{
    background: qlineargradient(x1:0,y1:0,x2:0.35,y2:1,
        stop:0 #1b3a5c, stop:0.55 {BG_TOP}, stop:1 {BG_BOT});
}}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#cell {{ background: {CARD_SOFT}; border: 1px solid {BORDER}; border-radius: 9px; }}
QFrame#chip {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#sep {{ background: {BORDER}; max-width: 1px; min-width: 1px; }}
QFrame#logochip {{ background: #e6f0fb; border: 1px solid {BORDER}; border-radius: 8px; }}

QLabel#brand {{ font-size: 22px; font-weight: 800; color: {TEXT}; letter-spacing: 1px; }}
QLabel#brandsub {{ color: {INDIGO}; font-family: {MONO}; font-size: 12px; font-weight: 700; letter-spacing: 2px; }}
QLabel#madeby {{ color: {INDIGO}; font-family: {MONO}; font-size: 17px; font-weight: 800; letter-spacing: 2px; }}
QLabel[role="field"] {{ color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }}
QLabel[role="celltitle"] {{ color: {TEXT}; font-size: 12px; font-weight: 800; letter-spacing: 1.5px; }}
QLabel[role="hint"] {{ color: {MUTED}; font-size: 10px; font-weight: 600; }}
QLabel[role="metric_t"] {{ color: {MUTED}; font-family: {MONO}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; }}
QLabel[role="metric_v"] {{ font-family: {MONO}; font-size: 21px; font-weight: 800; letter-spacing: 0.5px; color: {TEXT}; }}
QLabel[role="fwval"] {{ color: {TEXT}; font-size: 12px; }}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {CARD_SOFT}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 11px; min-height: 18px; selection-background-color: {INDIGO}; selection-color: #06243a;
    color: {TEXT}; font-weight: 600; font-family: {MONO};
}}
QComboBox:hover, QLineEdit:hover {{ border-color: {INDIGO}; }}
QComboBox:focus, QLineEdit:focus {{ border-color: {INDIGO}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; color: {TEXT};
    selection-background-color: {INDIGO}; selection-color: #06243a; outline: none;
}}

QPushButton {{
    background: {CARD_SOFT}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 8px 16px; color: {TEXT}; font-weight: 700;
}}
QPushButton:hover {{ border-color: {INDIGO}; color: {INDIGO}; }}
QPushButton:pressed {{ background: #0a1929; }}
QPushButton:disabled {{ color: #50708f; border-color: #1d3850; }}

QPushButton#primary {{ background: {GRAD_PRIMARY}; border: none; color: #042435; font-weight: 800; padding: 9px 20px; border-radius: 9px; }}
QPushButton#primary:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #5ad8f4, stop:1 {VIOLET}); }}
QPushButton#primary:disabled {{ background: {CARD_SOFT}; color: #50708f; }}

QPushButton#stop {{
    background: {GRAD_STOP}; border: none; color: #fff;
    font-size: 16px; font-weight: 900; letter-spacing: 3px; border-radius: 10px;
}}
QPushButton#stop:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f43f5e, stop:1 #c01038); }}

QLabel#pill {{
    border-radius: 8px; padding: 6px 16px; font-family: {MONO}; font-weight: 800; font-size: 11px;
    letter-spacing: 1.5px; background: rgba(255,92,122,0.16); color: #ff8095;
    border: 1px solid rgba(255,92,122,0.55);
}}
QLabel#pill[on="true"] {{ background: {GRAD_OK}; color: #04231a; border: none; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {INDIGO}; padding: 5px 9px; border-radius: 6px; }}

QPlainTextEdit {{
    background: #08131f; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 10px; font-family: {MONO}; font-size: 12px;
    color: #b9e9f4; selection-background-color: {INDIGO}; selection-color: #06243a;
}}
QLabel#fwkey {{ color: {MUTED}; font-weight: 700; font-size: 12px; font-family: {MONO}; }}
QLabel#fwval {{ color: {TEXT}; font-weight: 600; font-size: 12px; }}

QCheckBox {{ color: {TEXT}; font-weight: 600; spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {BORDER}; background: {CARD_SOFT}; }}
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


def _shadow(widget, blur=26, dy=8, alpha=120):
    eff = QtWidgets.QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur); eff.setOffset(0, dy)
    eff.setColor(QtGui.QColor(2, 8, 16, alpha))
    widget.setGraphicsEffect(eff)


class HudCard(QtWidgets.QFrame):
    """Panel with translucent cyan HUD corner brackets (QDD look)."""
    _BR = QtGui.QColor(60, 201, 232, 175)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pen = QtGui.QPen(self._BR); pen.setWidthF(1.6)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap); p.setPen(pen)
        m, L = 7, 15
        r = self.rect().adjusted(m, m, -m, -m)
        x1, y1, x2, y2 = r.left(), r.top(), r.right(), r.bottom()
        for (cx, cy, dx, dy) in ((x1, y1, 1, 1), (x2, y1, -1, 1),
                                 (x1, y2, 1, -1), (x2, y2, -1, -1)):
            p.drawLine(cx, cy, cx + dx * L, cy)
            p.drawLine(cx, cy, cx, cy + dy * L)
        p.end()


__all__ = ['BG_TOP', 'BG_BOT', 'SCROLL_BG', 'CARD', 'CARD_SOFT', 'BORDER', 'TEXT', 'MUTED',
           'SILVER', 'INDIGO', 'VIOLET', 'INDIGO_DK', 'ACCENT', 'C_BLUE', 'C_CORAL', 'C_VIOLET',
           'C_INDIGO', 'C_CYAN', 'C_AMBER', 'C_GREEN', 'C_TEAL', 'MONO', 'GRAD_PRIMARY',
           'GRAD_STOP', 'GRAD_OK', 'STYLE', '_shadow', 'HudCard', 'THEME_NAME']
