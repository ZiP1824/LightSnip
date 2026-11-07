"""Shared light theme for configuration, dialogs and application controls."""
from pathlib import Path
import sys
from PySide6.QtCore import Qt,QPoint,QRect,QRectF,QSize
from PySide6.QtGui import QColor,QGuiApplication,QPainter
from PySide6.QtWidgets import (QComboBox,QFontComboBox,QStyledItemDelegate,QFrame,
    QListView,QVBoxLayout,QAbstractItemView,QStyle)
from shiboken6 import isValid

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))


class _OptionDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):
        self.initStyleOption(option,index)
        width=option.fontMetrics.horizontalAdvance(option.text)+24
        if not option.icon.isNull():width+=24
        return QSize(width,32)

    def paint(self,painter,option,index):
        self.initStyleOption(option,index)
        enabled=bool(index.flags()&Qt.ItemFlag.ItemIsEnabled)
        active=bool(option.state&(QStyle.StateFlag.State_Selected|QStyle.StateFlag.State_MouseOver))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if active and enabled:
            painter.setBrush(QColor('#eaf2ff'))
            painter.drawRoundedRect(option.rect.adjusted(0,1,0,-1),5,5)
        text_rect=option.rect.adjusted(10,0,-10,0)
        if not option.icon.isNull():
            option.icon.paint(painter,QRect(text_rect.left(),text_rect.center().y()-8,16,16))
            text_rect.adjust(24,0,0,0)
        painter.setFont(option.font)
        painter.setPen(QColor('#a3afbf' if not enabled else '#216fdb' if active else '#263449'))
        text=option.fontMetrics.elidedText(option.text,Qt.TextElideMode.ElideRight,text_rect.width())
        painter.drawText(text_rect,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,text)
        painter.restore()


class _OptionList(QListView):
    def mouseMoveEvent(self,event):
        super().mouseMoveEvent(event)
        index=self.indexAt(event.position().toPoint())
        if index.isValid() and index.flags()&Qt.ItemFlag.ItemIsEnabled:self.setCurrentIndex(index)

    def keyPressEvent(self,event):
        if event.key() in [Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_Space]:
            self.window().choose(self.currentIndex())
            event.accept()
        elif event.key()==Qt.Key.Key_Escape:
            self.window().hide()
            event.accept()
        else:super().keyPressEvent(event)


class _ComboPopup(QFrame):
    def __init__(self,combo):
        super().__init__(combo,Qt.WindowType.Popup|Qt.WindowType.FramelessWindowHint|Qt.WindowType.NoDropShadowWindowHint)
        self.combo=combo
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName('comboPopup')
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet('QFrame#comboPopup {background:transparent;border:0;padding:0;}')
        layout=QVBoxLayout(self)
        layout.setContentsMargins(4,4,4,4)
        layout.setSpacing(0)
        self.list=_OptionList(self)
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setMinimumSize(0,0)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setModel(combo.model())
        self.list.setItemDelegate(_OptionDelegate(self.list))
        self.list.setStyleSheet('QListView {background:transparent;border:0;padding:0;margin:0;outline:0;} QListView::item {background:transparent;border:0;padding:0;margin:0;}')
        self.list.viewport().setStyleSheet('background:transparent;border:0;')
        self.list.clicked.connect(self.choose)
        layout.addWidget(self.list)

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(),Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor('#dce3ed'))
        painter.setBrush(QColor('white'))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),8,8)

    def choose(self,index):
        if not index.isValid() or not index.flags()&Qt.ItemFlag.ItemIsEnabled:return
        row=index.row()
        self.hide()
        self.combo.setCurrentIndex(row)
        self.combo.activated.emit(row)
        self.combo.textActivated.emit(self.combo.itemText(row))

    def hideEvent(self,event):
        if isValid(self.combo):QComboBox.hidePopup(self.combo)
        super().hideEvent(event)


def _popup(combo):
    if not hasattr(combo,'_themed_popup') or not isValid(combo._themed_popup):combo._themed_popup=_ComboPopup(combo)
    return combo._themed_popup


def _show_popup(combo):
    if not combo.isEnabled() or not combo.count():return
    popup=_popup(combo)
    view=popup.list
    view.setModel(combo.model())
    view.setRootIndex(combo.rootModelIndex())
    view.setModelColumn(combo.modelColumn())
    anchor=QRect(combo.mapToGlobal(QPoint()),combo.size())
    screen=QGuiApplication.screenAt(anchor.center()) or combo.screen()
    available=screen.availableGeometry().adjusted(4,4,-4,-4)
    width=min(max(combo.width(),view.sizeHintForColumn(combo.modelColumn())+8),available.width())
    wanted=min(combo.count(),combo.maxVisibleItems())*32+8
    below=available.bottom()-anchor.bottom()-4
    above=anchor.top()-available.top()-4
    if wanted<=below or below>=above:
        height=min(wanted,max(40,below))
        y=anchor.bottom()+5
    else:
        height=min(wanted,max(40,above))
        y=anchor.top()-height-4
    height=min(height,available.height())
    x=max(available.left(),min(anchor.left(),available.right()-width+1))
    y=max(available.top(),min(y,available.bottom()-height+1))
    popup.setGeometry(x,y,width,height)
    index=combo.model().index(combo.currentIndex(),combo.modelColumn(),combo.rootModelIndex())
    view.setCurrentIndex(index)
    popup.show()
    view.scrollTo(index,QAbstractItemView.ScrollHint.EnsureVisible)
    view.setFocus(Qt.FocusReason.PopupFocusReason)


class ThemedComboBox(QComboBox):
    def view(self):return _popup(self).list
    def showPopup(self):_show_popup(self)
    def hidePopup(self):
        if hasattr(self,'_themed_popup') and isValid(self._themed_popup):self._themed_popup.hide()
        super().hidePopup()


class ThemedFontComboBox(QFontComboBox):
    def view(self):return _popup(self).list
    def showPopup(self):_show_popup(self)
    def hidePopup(self):
        if hasattr(self,'_themed_popup') and isValid(self._themed_popup):self._themed_popup.hide()
        super().hidePopup()


LIGHT_STYLE='''
QWidget {font-family:"Microsoft YaHei UI";font-size:13px;color:#263449;}
QMainWindow,QDialog,QWidget#home {background:#f4f6fa;}
QLabel {background:transparent;}
QLabel#muted {color:#7a879a;font-size:12px;}
QLabel#title {font-size:26px;font-weight:600;}
QWidget#settingsSidebar {background:white;border-right:1px solid #e8edf4;}
QListWidget {background:white;border:0;outline:0;padding:16px 8px 0;}
QListWidget::item {height:42px;padding:0 10px;border:0;border-radius:7px;color:#526176;}
QListWidget::item:hover {background:#eff5ff;color:#2675dc;}
QListWidget::item:selected {background:#3286ff;color:white;}
QFrame#card {background:white;border:1px solid #e6ebf2;border-radius:11px;}
QPushButton {background:white;border:1px solid #dce3ed;border-radius:7px;padding:7px 12px;min-height:18px;}
QPushButton:hover {background:#f0f6ff;border-color:#a8c9fa;color:#236ed0;}
QPushButton:pressed {background:#e4efff;border-color:#80b1fa;}
QPushButton:focus {border-color:#85b4fa;}
QPushButton#primary {background:#3286ff;color:white;border:1px solid #3286ff;}
QPushButton#primary:hover {background:#2479f1;border-color:#2479f1;}
QPushButton#primary:pressed {background:#1869d9;border-color:#1869d9;}
QPushButton:disabled {background:#f5f7fa;color:#aab4c3;border-color:#e6ebf2;}
QToolBar {background:white;spacing:4px;border:0;padding:5px;}
QToolButton {background:transparent;padding:5px;color:#28364b;border:0;border-radius:5px;}
QToolButton:hover {background:#edf4ff;}
QToolButton:checked {background:#dfecff;color:#2474df;}
QTextEdit,QPlainTextEdit,QLineEdit,QKeySequenceEdit,QComboBox,QSpinBox,QDoubleSpinBox {
 background:white;border:1px solid #dce3ed;border-radius:7px;selection-background-color:#dceaff;selection-color:#234d8b;
}
QLineEdit,QKeySequenceEdit {padding:6px 10px;min-height:20px;}
QLineEdit:hover,QKeySequenceEdit:hover,QComboBox:hover,QSpinBox:hover,QDoubleSpinBox:hover {border-color:#b7c9df;}
QLineEdit:focus,QKeySequenceEdit:focus,QTextEdit:focus,QPlainTextEdit:focus,QComboBox:focus,QSpinBox:focus,QDoubleSpinBox:focus {border-color:#78aef9;}
QLineEdit:disabled,QComboBox:disabled,QSpinBox:disabled {background:#f5f7fa;color:#a3afbf;}
QKeySequenceEdit {border:0;background:transparent;padding:0;min-height:34px;}
QKeySequenceEdit QLineEdit {border:1px solid #dce3ed;background:#f8fafd;border-radius:7px;padding:6px 10px;min-height:20px;}
QTextEdit,QPlainTextEdit {padding:10px;}
QComboBox {background:#f8fafd;padding:5px 30px 5px 10px;min-height:20px;min-width:96px;}
QComboBox::drop-down {subcontrol-origin:border;subcontrol-position:top right;width:28px;border:0;background:transparent;}
QComboBox::down-arrow {image:url("$DOWN");width:12px;height:12px;}
QComboBox QAbstractItemView {background:white;border:0;padding:0;outline:0;selection-background-color:#eaf2ff;selection-color:#216fdb;}
QComboBox QAbstractItemView::item {padding:6px 10px;min-height:20px;border:0;border-radius:4px;}
QComboBox QAbstractItemView::item:selected {background:#eaf2ff;color:#216fdb;}
QSpinBox,QDoubleSpinBox {background:#f8fafd;padding:5px 30px 5px 10px;min-height:20px;}
QSpinBox::up-button,QDoubleSpinBox::up-button {subcontrol-origin:border;subcontrol-position:top right;width:24px;height:16px;border:0;border-left:1px solid #e3e9f2;border-top-right-radius:7px;background:transparent;}
QSpinBox::down-button,QDoubleSpinBox::down-button {subcontrol-origin:border;subcontrol-position:bottom right;width:24px;height:16px;border:0;border-left:1px solid #e3e9f2;border-bottom-right-radius:7px;background:transparent;}
QSpinBox::up-button:hover,QSpinBox::down-button:hover,QDoubleSpinBox::up-button:hover,QDoubleSpinBox::down-button:hover {background:#e7f0ff;}
QSpinBox::up-arrow,QDoubleSpinBox::up-arrow {image:url("$UP");width:12px;height:12px;}
QSpinBox::down-arrow,QDoubleSpinBox::down-arrow {image:url("$DOWN");width:12px;height:12px;}
QCheckBox {spacing:10px;min-height:22px;background:transparent;}
QCheckBox::indicator {width:18px;height:18px;border:1px solid #cdd7e5;border-radius:4px;background:white;}
QCheckBox::indicator:hover {border-color:#78aef9;background:#f6faff;}
QCheckBox::indicator:checked {border-color:#3286ff;background:#3286ff;image:url("$CHECK");}
QCheckBox::indicator:disabled {border-color:#e1e7ef;background:#f1f4f8;}
QSlider::groove:horizontal {height:4px;border:0;background:#e1e8f2;border-radius:2px;}
QSlider::sub-page:horizontal {background:#3286ff;border-radius:2px;}
QSlider::handle:horizontal {background:white;border:2px solid #3286ff;width:11px;margin:-5px 0;border-radius:7px;}
QScrollArea {border:0;background:transparent;}
QScrollBar:vertical {background:transparent;width:8px;margin:3px 0;}
QScrollBar::handle:vertical {background:#cdd7e5;border-radius:4px;min-height:28px;}
QScrollBar::handle:vertical:hover {background:#aabbd1;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;border:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
QScrollBar:horizontal {background:transparent;height:8px;margin:0 3px;}
QScrollBar::handle:horizontal {background:#cdd7e5;border-radius:4px;min-width:28px;}
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal {width:0;border:0;}
QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal {background:transparent;}
QMenu {background:white;border:1px solid #dce3ed;border-radius:7px;padding:5px;}
QMenu::item {padding:7px 22px;border-radius:4px;}
QMenu::item:selected {background:#eaf2ff;color:#216fdb;}
QMenu::separator {height:1px;background:#e8edf4;margin:5px 7px;}
QStatusBar {color:#7a879a;background:#f4f6fa;border:0;}
QToolTip {background:#263449;color:white;border:0;border-radius:5px;padding:6px 8px;font-size:12px;}
QSplitter::handle {background:#e6ebf2;}
'''.replace('$DOWN',(ROOT/'assets/ui/chevron-down.svg').as_posix()).replace('$UP',(ROOT/'assets/ui/chevron-up.svg').as_posix()).replace('$CHECK',(ROOT/'assets/ui/check-white.svg').as_posix())
