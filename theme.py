"""Theme: D · Industrial Amber — drop-in skin for SPG QDD Control."""
from PyQt6 import QtCore, QtGui, QtWidgets

THEME_NAME = "D · Industrial Amber"

BG_TOP    = "#1d1e20"
BG_BOT    = "#0f1011"
SCROLL_BG = "#191a1c"
CARD      = "#212327"
CARD_SOFT = "#171a1d"
BORDER    = "#3c3f44"
TEXT      = "#f0ead8"
MUTED     = "#9b9384"
INDIGO    = "#f5a623"
VIOLET    = "#ff7a18"
INDIGO_DK = "#d98b12"
ACCENT    = INDIGO
C_BLUE   = "#54b0e0"
C_CORAL  = "#ef5a45"
C_VIOLET = "#c79bff"
C_INDIGO = "#f5a623"
C_CYAN   = "#46c8d6"
C_AMBER  = "#f5a623"
C_GREEN  = "#8ec24a"
C_TEAL   = "#46c8d6"
MONO = '"JetBrains Mono","Consolas","Cascadia Mono","D2Coding",monospace'
GRAD_PRIMARY = "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f5a623, stop:1 #ff7a18)"
GRAD_STOP    = "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ef5a45, stop:1 #c0241a)"
GRAD_OK      = "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #a6d65a, stop:1 #6fae2a)"

STYLE = r'''
* {
    font-family: "Pretendard","Segoe UI","Malgun Gothic",sans-serif;
    font-size: 13px; color: #f0ead8;
}
QWidget#central { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #232427, stop:1 #0f1011); }

QFrame#card { background: #212327; border: 1px solid #3c3f44; border-radius: 5px; }
QFrame#cell { background: #171a1d; border: 1px solid #3c3f44; border-radius: 4px; }
QFrame#chip { background: #212327; border: 1px solid #3c3f44; border-radius: 4px; }
QFrame#sep { background: #3c3f44; max-width: 1px; min-width: 1px; }
QFrame#logochip { background: #ece6d8; border: 1px solid #3c3f44; border-radius: 8px; }

QLabel#brand { font-size: 22px; font-weight: 800; color: #f0ead8; letter-spacing: 2px; }
QLabel#brandsub { color: #f5a623; font-family: "JetBrains Mono","Consolas","Cascadia Mono","D2Coding",monospace; font-size: 12px; font-weight: 700; letter-spacing: 2px; }
QLabel[role="field"] { color: #9b9384; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }
QLabel[role="celltitle"] { color: #f0ead8; font-size: 12px; font-weight: 800; letter-spacing: 1.5px; }
QLabel[role="hint"] { color: #9b9384; font-size: 10px; font-weight: 600; }
QLabel[role="metric_t"] { color: #9b9384; font-family: "JetBrains Mono","Consolas","Cascadia Mono","D2Coding",monospace; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; }
QLabel[role="metric_v"] { font-family: "JetBrains Mono","Consolas","Cascadia Mono","D2Coding",monospace; font-size: 21px; font-weight: 800; letter-spacing: 0.5px; }
QLabel[role="fwval"] { color: #f0ead8; font-size: 12px; }

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    background: #171a1d; border: 1px solid #3c3f44; border-radius: 4px;
    padding: 7px 11px; min-height: 18px; selection-background-color: #f5a623; selection-color: #241a05;
    color: #f0ead8; font-weight: 600; font-family: "JetBrains Mono","Consolas","Cascadia Mono","D2Coding",monospace;
}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #f5a623; }
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #f5a623; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: #212327; border: 1px solid #3c3f44; border-radius: 4px; color: #f0ead8;
    selection-background-color: #f5a623; selection-color: #241a05; outline: none;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button { width: 14px; background: transparent; border: none; }

QPushButton {
    background: #26282c; border: 1px solid #3c3f44; border-radius: 4px;
    padding: 8px 16px; color: #f0ead8; font-weight: 700;
}
QPushButton:hover { border-color: #f5a623; color: #f5a623; }
QPushButton:pressed { background: #101113; }
QPushButton:disabled { color: #6a655a; border-color: #2a2c30; }

QPushButton#primary { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f5a623, stop:1 #ff7a18); border: none; color: #241a05; font-weight: 800; padding: 9px 20px; border-radius: 4px; }
QPushButton#primary:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ffbe4a, stop:1 #f5901a); }
QPushButton#primary:disabled { background: #26282c; color: #6a655a; }

QPushButton#start { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f5a623, stop:1 #ff7a18); border: none; color: #241a05; font-weight: 800; border-radius: 4px; padding: 8px 18px; }
QPushButton#start:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ffbe4a, stop:1 #f5901a); }
QPushButton#start:disabled { background: #26282c; color: #6a655a; }

QPushButton#stop {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ef5a45, stop:1 #c0241a); border: none; color: #fff;
    font-size: 16px; font-weight: 900; letter-spacing: 3px; border-radius: 5px;
}
QPushButton#stop:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ff6a52, stop:1 #a81810); }

QLabel#pill {
    border-radius: 4px; padding: 6px 16px; font-family: "JetBrains Mono","Consolas","Cascadia Mono","D2Coding",monospace; font-weight: 800; font-size: 11px;
    letter-spacing: 1.5px; background: rgba(239,90,69,0.18); color: #ff8a78; border: 1px solid rgba(239,90,69,0.6);
}
QLabel#pill[on="true"] { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #a6d65a, stop:1 #6fae2a); color: #1c2406; border: none; }
QToolTip { background: #212327; color: #f0ead8; border: 1px solid #f5a623; padding: 5px 9px; border-radius: 6px; }

QTabWidget::pane { border: none; }
QTabBar::tab {
    background: #26282c; color: #9b9384; font-weight: 800; font-size: 13px;
    padding: 8px 18px; margin-right: 6px; border-radius: 4px; border: 1px solid #3c3f44;
}
QTabBar::tab:selected { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f5a623, stop:1 #ff7a18); color: #241a05; border: none; }
QTabBar::tab:hover:!selected { color: #f5a623; border-color: #f5a623; }

QPushButton#rec { background: #26282c; border: 1px solid #3c3f44; border-radius: 4px; padding: 8px 16px; color: #f0ead8; font-weight: 800; }
QPushButton#rec:hover { border-color: #ef5a45; color: #ef5a45; }
QPushButton#rec[recording="true"] { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ef5a45, stop:1 #c0241a); border: none; color: #fff; }

QPlainTextEdit {
    background: #0d0e10; border: 1px solid #3c3f44; border-radius: 4px;
    padding: 10px; font-family: "JetBrains Mono","Consolas","Cascadia Mono","D2Coding",monospace; font-size: 12px;
    color: #ffd591; selection-background-color: #f5a623; selection-color: #241a05;
}
QLabel#fwkey { color: #9b9384; font-weight: 700; font-size: 12px; font-family: "JetBrains Mono","Consolas","Cascadia Mono","D2Coding",monospace; }
QLabel#fwval { color: #f0ead8; font-weight: 600; font-size: 12px; }
QLabel#linklbl { color: #f5a623; font-weight: 700; }

QCheckBox { color: #f0ead8; font-weight: 600; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px; border: 1px solid #3c3f44; background: #171a1d; }
QCheckBox::indicator:hover { border-color: #f5a623; }
QCheckBox::indicator:checked { background: #f5a623; border: 1px solid #f5a623; }

QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: #3c3f44; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #f5a623; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal { background: #3c3f44; border-radius: 5px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: #f5a623; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QMessageBox, QDialog { background: #212327; }
QMessageBox QLabel { color: #f0ead8; font-size: 13px; background: transparent; }
QMessageBox QPushButton { min-width: 72px; padding: 7px 18px; }
'''


def _shadow(widget, blur=26, dy=8, alpha=140):
    eff = QtWidgets.QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur); eff.setOffset(0, dy)
    eff.setColor(QtGui.QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)


class HudCard(QtWidgets.QFrame):
    """Panel that paints a per-theme corner motif over the QSS card fill."""
    _STYLE = "heavy"
    _BR = QtGui.QColor(245, 166, 35, 190)
    _GRID = None              # (r,g,b,a) or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self._STYLE == "none":
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        r = self.rect().adjusted(7, 7, -7, -7)
        x1, y1, x2, y2 = r.left(), r.top(), r.right(), r.bottom()
        corners = ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1))

        if self._STYLE == "dimension" and self._GRID:
            gp = QtGui.QPen(QtGui.QColor(*self._GRID)); gp.setWidthF(1.0); p.setPen(gp)
            step = 46
            gx = x1 + step
            while gx < x2:
                p.drawLine(gx, y1, gx, y2); gx += step
            gy = y1 + step
            while gy < y2:
                p.drawLine(x1, gy, x2, gy); gy += step

        pen = QtGui.QPen(self._BR)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)

        if self._STYLE == "dimension":
            pen.setWidthF(1.2); p.setPen(pen)
            p.drawRect(r); L = 10
            for (cx, cy, dx, dy) in corners:
                p.drawLine(cx - dx*3, cy, cx - dx*3 - dx*L, cy)
        elif self._STYLE == "heavy":
            pen.setWidthF(2.6); p.setPen(pen); L = 18
            for (cx, cy, dx, dy) in corners:
                p.drawLine(cx, cy, cx + dx*L, cy); p.drawLine(cx, cy, cx, cy + dy*L)
            p.setBrush(QtGui.QBrush(self._BR)); p.setPen(QtCore.Qt.PenStyle.NoPen)
            for (cx, cy, dx, dy) in corners:
                p.drawEllipse(QtCore.QPointF(cx + dx*9, cy + dy*9), 2.6, 2.6)
        elif self._STYLE == "corner_accent":
            pen.setWidthF(3.0); p.setPen(pen); L = 26
            for (cx, cy, dx, dy) in ((x1, y1, 1, 1), (x2, y2, -1, -1)):
                p.drawLine(cx, cy, cx + dx*L, cy); p.drawLine(cx, cy, cx, cy + dy*L)
        elif self._STYLE == "ticks":
            pen.setWidthF(1.3); p.setPen(pen); L = 12
            for (cx, cy, dx, dy) in corners:
                p.drawLine(cx, cy, cx + dx*L, cy); p.drawLine(cx, cy, cx, cy + dy*L)
        elif self._STYLE == "glass":
            grad = QtGui.QLinearGradient(x1, 0, x2, 0)
            c = QtGui.QColor(*self._GRID) if self._GRID else QtGui.QColor(255,255,255,90)
            edge = QtGui.QColor(c); edge.setAlpha(0)
            grad.setColorAt(0.0, edge); grad.setColorAt(0.5, c); grad.setColorAt(1.0, edge)
            gp = QtGui.QPen(QtGui.QBrush(grad), 1.6); p.setPen(gp)
            p.drawLine(x1 + 10, y1, x2 - 10, y1)
        else:  # "hud"
            pen.setWidthF(1.6); p.setPen(pen); L = 15
            for (cx, cy, dx, dy) in corners:
                p.drawLine(cx, cy, cx + dx*L, cy); p.drawLine(cx, cy, cx, cy + dy*L)
        p.end()


__all__ = ['BG_TOP', 'BG_BOT', 'SCROLL_BG', 'CARD', 'CARD_SOFT', 'BORDER', 'TEXT', 'MUTED', 'INDIGO', 'VIOLET', 'INDIGO_DK', 'ACCENT', 'C_BLUE', 'C_CORAL', 'C_VIOLET', 'C_INDIGO', 'C_CYAN', 'C_AMBER', 'C_GREEN', 'C_TEAL', 'MONO', 'GRAD_PRIMARY', 'GRAD_STOP', 'GRAD_OK', 'STYLE', '_shadow', 'HudCard', 'THEME_NAME']
