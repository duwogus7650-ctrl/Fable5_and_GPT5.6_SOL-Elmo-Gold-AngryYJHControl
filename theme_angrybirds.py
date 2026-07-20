"""Theme: Angry Birds — playful slingshot skin for AngryYJH Control.

Bright sky + cream cards, Red bird header, Yellow slingshot primary, Green pig OK,
dark charcoal text with monospace numeric readouts (kept for dashboard legibility).
Drop-in API-compatible with theme.py (same names, STYLE, HudCard).
"""
from PyQt6 import QtCore, QtGui, QtWidgets

THEME_NAME = "Angry Birds"

# palette
BG_TOP    = "#afe3f7"   # sky
BG_BOT    = "#ffe9b8"   # sand/cream
SCROLL_BG = "#fff6e0"
CARD      = "#fffdf6"    # cream card
CARD_SOFT = "#fff3d8"    # soft cell
BORDER    = "#e6b23c"    # amber-gold edge
TEXT      = "#2b211a"    # dark charcoal-brown
MUTED     = "#8a7a63"
RED       = "#e52521"    # Red bird
RED_DK    = "#b81f1c"
YELLOW    = "#ffc72c"    # Chuck / slingshot
YELLOW_DK = "#e9a400"
GREEN     = "#7ab800"    # pig green
GREEN_DK  = "#5f9200"
SKY       = "#39a9db"
INDIGO    = RED          # ACCENT alias used by shell
VIOLET    = YELLOW
INDIGO_DK = RED_DK
ACCENT    = RED
C_BLUE   = "#39a9db"
C_CORAL  = "#e52521"
C_VIOLET = "#ffc72c"
C_INDIGO = "#e52521"
C_CYAN   = "#2bb7c4"
C_AMBER  = "#ffc72c"
C_GREEN  = "#7ab800"
C_TEAL   = "#2bb7c4"
MONO = '"JetBrains Mono","Consolas","Cascadia Mono","D2Coding",monospace'
GRAD_PRIMARY = "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ffd24a, stop:1 #f5a100)"
GRAD_STOP    = "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f04438, stop:1 #b81f1c)"
GRAD_OK      = "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #96d030, stop:1 #5f9200)"

STYLE = r'''
* {
    font-family: "Baloo 2","Fredoka","Segoe UI","Malgun Gothic",sans-serif;
    font-size: 13px; color: #2b211a;
}
QWidget#central { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #afe3f7, stop:1 #ffe9b8); }

QFrame#card { background: #ffffff; border: 2px solid #e6b23c; border-radius: 12px; }
QFrame#cell { background: #fff6de; border: 2px solid #f0c85a; border-radius: 10px; }
QFrame#chip { background: #fffdf6; border: 2px solid #e6b23c; border-radius: 8px; }
QFrame#sep { background: #e6b23c; max-width: 2px; min-width: 2px; }
QFrame#logochip { background: #ffffff; border: 2px solid #e52521; border-radius: 12px; }

QLabel#brand { font-size: 24px; font-weight: 900; color: #e52521; letter-spacing: 1px; }
QLabel#brandsub { color: #5f9200; font-family: "JetBrains Mono","Consolas",monospace; font-size: 12px; font-weight: 800; letter-spacing: 2px; }
QLabel#madeby { color: #8a7a63; font-size: 11px; font-weight: 700; font-style: italic; }
QLabel[role="field"] { color: #8a7a63; font-size: 11px; font-weight: 800; letter-spacing: 0.5px; }
QLabel[role="celltitle"] { color: #e52521; font-size: 13px; font-weight: 900; letter-spacing: 1px; }
QLabel[role="hint"] { color: #8a7a63; font-size: 10px; font-weight: 700; }
QLabel[role="metric_t"] { color: #8a7a63; font-family: "JetBrains Mono","Consolas",monospace; font-size: 10px; font-weight: 800; letter-spacing: 1.5px; }
QLabel[role="metric_v"] { font-family: "JetBrains Mono","Consolas",monospace; font-size: 22px; font-weight: 900; letter-spacing: 0.5px; color: #2b211a; }
QLabel[role="fwval"] { color: #2b211a; font-size: 12px; }

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    background: #fffaf0; border: 2px solid #e6b23c; border-radius: 8px;
    padding: 7px 11px; min-height: 18px; selection-background-color: #ffc72c; selection-color: #2b211a;
    color: #2b211a; font-weight: 700; font-family: "JetBrains Mono","Consolas",monospace;
}
QComboBox:hover, QLineEdit:hover { border-color: #e52521; }
QComboBox:focus, QLineEdit:focus { border-color: #e52521; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: #fffdf6; border: 2px solid #e6b23c; border-radius: 8px; color: #2b211a;
    selection-background-color: #ffc72c; selection-color: #2b211a; outline: none;
}

QPushButton {
    background: #fff3d8; border: 2px solid #e6b23c; border-radius: 8px;
    padding: 8px 16px; color: #2b211a; font-weight: 800;
}
QPushButton:hover { border-color: #e52521; color: #e52521; }
QPushButton:pressed { background: #ffe6b0; }
QPushButton:disabled { color: #b9a67f; border-color: #ecd8a4; }

QPushButton#primary { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ffd24a, stop:1 #f5a100); border: 2px solid #e9a400; color: #2b211a; font-weight: 900; padding: 9px 20px; border-radius: 9px; }
QPushButton#primary:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ffe07a, stop:1 #ffb01f); }
QPushButton#primary:disabled { background: #f2e4c2; color: #b9a67f; border-color: #ecd8a4; }

QPushButton#start { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #96d030, stop:1 #5f9200); border: none; color: #ffffff; font-weight: 900; border-radius: 9px; padding: 8px 18px; }
QPushButton#start:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #a8e043, stop:1 #6fae10); }

QPushButton#stop {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f04438, stop:1 #b81f1c); border: none; color: #fff;
    font-size: 16px; font-weight: 900; letter-spacing: 3px; border-radius: 10px;
}
QPushButton#stop:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ff5a4d, stop:1 #a01916); }

QLabel#pill {
    border-radius: 9px; padding: 6px 16px; font-family: "JetBrains Mono","Consolas",monospace; font-weight: 900; font-size: 11px;
    letter-spacing: 1.5px; background: rgba(229,37,33,0.14); color: #b81f1c; border: 2px solid rgba(229,37,33,0.5);
}
QLabel#pill[on="true"] { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #96d030, stop:1 #5f9200); color: #ffffff; border: none; }
QLabel#pill[status="active"] { background: #dff4ff; color: #176887; border-color: #55a9cb; }
QLabel#pill[status="ready"] { background: #fff0ad; color: #735200; border-color: #e6b23c; }
QLabel#pill[status="success"] { background: #6fae10; color: #ffffff; border-color: #96d030; }
QLabel#pill[status="error"] { background: #ffe0d8; color: #a01916; border-color: #e52521; }
QLabel#pill[status="neutral"] { background: #fff3d8; color: #8a6e4d; border-color: #d6b36c; }
QToolTip { background: #fffdf6; color: #2b211a; border: 2px solid #e52521; padding: 5px 9px; border-radius: 8px; }

QTableWidget#expertEvidenceTable {
    background: #fffaf0; alternate-background-color: #fff3d8;
    color: #2b211a; gridline-color: #e6b23c;
    border: 2px solid #e6b23c; border-radius: 8px;
    selection-background-color: #fff3d8; selection-color: #2b211a;
    outline: none; font-family: "JetBrains Mono","Consolas",monospace;
}
QTableWidget#expertEvidenceTable::item { padding: 6px; }
QTableWidget#expertEvidenceTable QHeaderView::section {
    background: #ffe9b8; color: #b81f1c; border: none;
    border-right: 1px solid #e6b23c; border-bottom: 1px solid #e6b23c;
    padding: 7px 5px; font-weight: 900;
}
QTableWidget#expertEvidenceTable QTableCornerButton::section {
    background: #ffe9b8; border: 1px solid #e6b23c;
}

QTabWidget::pane { border: none; }
QTabBar::tab {
    background: #fff3d8; color: #8a7a63; font-weight: 900; font-size: 13px;
    padding: 8px 18px; margin-right: 6px; border-radius: 8px; border: 2px solid #e6b23c;
}
QTabBar::tab:selected { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ffd24a, stop:1 #f5a100); color: #2b211a; border: none; }
QTabBar::tab:hover:!selected { color: #e52521; border-color: #e52521; }

QPushButton#rec { background: #fff3d8; border: 2px solid #e6b23c; border-radius: 8px; padding: 8px 16px; color: #2b211a; font-weight: 900; }
QPushButton#rec:hover { border-color: #e52521; color: #e52521; }
QPushButton#rec[recording="true"] { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f04438, stop:1 #b81f1c); border: none; color: #fff; }

QPlainTextEdit {
    background: #2b211a; border: 2px solid #e6b23c; border-radius: 8px;
    padding: 10px; font-family: "JetBrains Mono","Consolas",monospace; font-size: 12px;
    color: #ffd24a; selection-background-color: #ffc72c; selection-color: #2b211a;
}
QLabel#fwkey { color: #8a7a63; font-weight: 800; font-size: 12px; font-family: "JetBrains Mono","Consolas",monospace; }
QLabel#fwval { color: #2b211a; font-weight: 700; font-size: 12px; }
QLabel#linklbl { color: #e52521; font-weight: 800; }

QCheckBox { color: #2b211a; font-weight: 700; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 6px; border: 2px solid #e6b23c; background: #fffaf0; }
QCheckBox::indicator:hover { border-color: #e52521; }
QCheckBox::indicator:checked { background: #7ab800; border: 2px solid #5f9200; }

QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: #e6b23c; border-radius: 6px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #e52521; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: #e6b23c; border-radius: 6px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: #e52521; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QStatusBar { color: #2b211a; font-weight: 700; }
'''


def _shadow(widget, blur=26, dy=8, alpha=70):
    eff = QtWidgets.QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur); eff.setOffset(0, dy)
    eff.setColor(QtGui.QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)


class HudCard(QtWidgets.QFrame):
    """Cream panel with Red-bird corner brackets."""
    _STYLE = "heavy"
    _BR = QtGui.QColor(229, 37, 33, 220)   # Angry Birds red
    _GRID = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        r = self.rect().adjusted(8, 8, -8, -8)
        x1, y1, x2, y2 = r.left(), r.top(), r.right(), r.bottom()
        corners = ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1))
        pen = QtGui.QPen(self._BR); pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        pen.setWidthF(3.0); p.setPen(pen); L = 18
        for (cx, cy, dx, dy) in corners:
            p.drawLine(cx, cy, cx + dx * L, cy); p.drawLine(cx, cy, cx, cy + dy * L)
        p.setBrush(QtGui.QBrush(self._BR)); p.setPen(QtCore.Qt.PenStyle.NoPen)
        for (cx, cy, dx, dy) in corners:
            p.drawEllipse(QtCore.QPointF(cx + dx * 9, cy + dy * 9), 3.0, 3.0)
        p.end()


__all__ = ['BG_TOP', 'BG_BOT', 'SCROLL_BG', 'CARD', 'CARD_SOFT', 'BORDER', 'TEXT', 'MUTED',
           'INDIGO', 'VIOLET', 'INDIGO_DK', 'ACCENT', 'RED', 'YELLOW', 'GREEN', 'SKY',
           'C_BLUE', 'C_CORAL', 'C_VIOLET', 'C_INDIGO', 'C_CYAN', 'C_AMBER', 'C_GREEN', 'C_TEAL',
           'MONO', 'GRAD_PRIMARY', 'GRAD_STOP', 'GRAD_OK', 'STYLE', '_shadow', 'HudCard', 'THEME_NAME']
