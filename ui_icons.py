from pathlib import Path
import sys
from PySide6.QtCore import Qt,QSize,QByteArray
from PySide6.QtGui import QIcon,QPixmap,QPainter,QColor
from PySide6.QtSvg import QSvgRenderer

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))


def lucide(name,color='#000000',size=20):
    svg=(ROOT/'assets'/'lucide'/(name+'.svg')).read_text(encoding='utf-8')
    svg=svg.replace('currentColor',color).replace('stroke-width="2"','stroke-width="1.8"')
    renderer=QSvgRenderer(QByteArray(svg.encode()))
    icon=QIcon()
    for ratio in [1,2,3]:
        pix=QPixmap(size*ratio,size*ratio)
        pix.fill(Qt.GlobalColor.transparent)
        p=QPainter(pix)
        renderer.render(p)
        p.end()
        pix.setDevicePixelRatio(ratio)
        icon.addPixmap(pix)
    return icon


TOOLBAR_STYLE='''
QToolBar {background:#fafafa;border:1px solid #d5d8de;border-radius:7px;padding:3px;spacing:1px;}
QToolButton {background:transparent;border:0;border-radius:4px;padding:5px;color:#343a40;}
QToolButton:hover {background:#e8edf3;} QToolButton:checked {background:#deebfc;}
QToolButton::menu-indicator {image:none;width:0;}
QToolBar::separator {background:#dfe2e6;width:1px;margin:6px 5px;}
QLabel {color:#53657b;font-size:12px;background:transparent;border:0;}
QComboBox {background:#eff1f4;border:0;border-radius:4px;padding:2px 7px;min-height:20px;}
'''
