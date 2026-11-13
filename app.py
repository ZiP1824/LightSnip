if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()

import ctypes
import math
from dataclasses import dataclass, replace
from pathlib import Path
import sys
from file_names import choose_save_path,remember_saved_file,save_directory,save_new_png
from PySide6.QtCore import (Qt, QPoint, QPointF, QEvent, QRect, QSize, QTimer, Signal, QObject,
                            QRunnable, QThreadPool, QBuffer, QIODevice, QAbstractNativeEventFilter)
from PySide6.QtGui import (QPixmap, QImage, QPainter, QColor, QPen, QFont, QIcon, QAction, QMouseEvent,
                           QKeySequence, QShortcut, QPolygon,QCursor,QTextDocument)
from PySide6.QtWidgets import (QApplication, QWidget, QMainWindow, QLabel,
    QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QScrollArea,
    QToolBar, QFileDialog, QMessageBox, QInputDialog, QColorDialog, QSpinBox,
    QDialog, QTextEdit, QPlainTextEdit, QComboBox, QSplitter, QSystemTrayIcon, QMenu)
from services import recognize, translate
from delayed_capture import CaptureCountdown
from settings_ui import preferences, flag, keys, LIGHT_STYLE, SettingsWindow,CAPTURE_ONLY_ACTIONS
from ui_icons import lucide, TOOLBAR_STYLE
from annotation_tools import AnnotationOptions,SelectionBorder,draw_arrow,tool_cursor,badge_icon,BORDER_WIDTH
from theme import ThemedComboBox
from window_detection import snapshot_windows
from element_detection import RegionScanner
from mosaic import MosaicEffect

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))


def icon():
    path = ROOT / 'assets' / 'icon.png'
    if path.exists():
        return QIcon(str(path))
    p = QPixmap(64, 64)
    p.fill(QColor('#102d37'))
    q = QPainter(p)
    q.setPen(QPen(QColor('#55dfbd'), 6))
    q.drawRect(17, 17, 30, 30)
    q.end()
    return QIcon(p)


def png_bytes(pix):
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pix.save(buf, 'PNG')
    return bytes(buf.data())


class JobSignals(QObject):
    result = Signal(str)
    error = Signal(str)


class Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn, self.signals = fn, JobSignals()

    def run(self):
        try:
            self.signals.result.emit(self.fn())
        except Exception as exc:
            self.signals.error.emit(str(exc))


class TextDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('轻截 · 文字翻译')
        self.resize(900, 580)
        self.jobs = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('文字留在本机；点击「联网翻译」才发送左侧文字到 MyMemory。'))
        note = QLabel('免登录 / 免密钥 · 匿名免费额度 5,000 字符/天（服务商计量）· 需要联网')
        note.setObjectName('muted')
        layout.addWidget(note)
        row = QHBoxLayout()
        self.source, self.target = ThemedComboBox(), ThemedComboBox()
        langs = [('简体中文', 'zh-CN'), ('英语', 'en'), ('日语', 'ja'), ('韩语', 'ko'), ('法语', 'fr'), ('德语', 'de')]
        self.source.addItem('自动判断（中英日韩）', 'auto')
        for label, code in langs:
            self.source.addItem(label, code)
            self.target.addItem(label, code)
        row.addWidget(self.source)
        row.addWidget(QLabel('→'))
        row.addWidget(self.target)
        self.go = QPushButton('联网翻译')
        self.go.setObjectName('primary')
        self.go.clicked.connect(self.do_translate)
        row.addWidget(self.go)
        layout.addLayout(row)
        split = QSplitter()
        self.original, self.output = QTextEdit(), QTextEdit()
        self.original.setPlaceholderText('输入或粘贴需要翻译的文字…')
        self.output.setPlaceholderText('译文将在这里显示')
        self.output.setReadOnly(True)
        split.addWidget(self.original)
        split.addWidget(self.output)
        layout.addWidget(split)
        self.status = QLabel('就绪')
        layout.addWidget(self.status)
        row2 = QHBoxLayout()
        for name, field in [('复制原文', self.original), ('复制译文', self.output)]:
            b = QPushButton(name)
            b.clicked.connect(lambda _, f=field: QApplication.clipboard().setText(f.toPlainText()))
            row2.addWidget(b)
        layout.addLayout(row2)

    def work(self, fn, done):
        job = Job(fn)
        self.jobs.append(job)
        job.signals.result.connect(done)
        job.signals.error.connect(self.failed)
        QThreadPool.globalInstance().start(job)

    def failed(self, message):
        self.go.setEnabled(True)
        self.status.setText('操作失败：' + message[:300])

    def do_translate(self):
        text, source, target = self.original.toPlainText(), self.source.currentData(), self.target.currentData()
        if not text.strip():
            self.status.setText('请先输入或识别文字。')
            return
        self.go.setEnabled(False)
        self.status.setText('正在翻译…')
        self.work(lambda: translate(text, source, target), self.translated)

    def translated(self, text):
        self.output.setPlainText(text)
        self.go.setEnabled(True)
        self.status.setText('翻译完成')

    def closeEvent(self, event):
        # Keep the receiver alive until worker completion; closing only hides the dialog.
        event.accept()


class OcrImageView(QScrollArea):
    def __init__(self,pix,parent=None):
        super().__init__(parent)
        self.source=pix.copy()
        self.source.setDevicePixelRatio(1)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignTop)
        self.setStyleSheet('QScrollArea {background:#f0f2f5;border:1px solid #dedfe3;border-radius:6px;}')
        self.image=QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMargin(12)
        self.image.setAccessibleName('截图图片')
        self.image.setStyleSheet('background:transparent;')
        self.setWidget(self.image)
        self.refresh()

    def refresh(self):
        if self.source.isNull():return
        width=max(1,min(self.source.width(),self.viewport().width()-26))
        scaled=self.source.scaledToWidth(width,Qt.TransformationMode.SmoothTransformation)
        self.image.setPixmap(scaled)
        self.image.setFixedSize(scaled.size()+QSize(24,24))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.refresh()


class OcrDialog(QDialog):
    def __init__(self,pix,parent=None):
        super().__init__(parent)
        self.setWindowTitle('轻截 · 文字识别')
        self.setWindowIcon(icon())
        self.setStyleSheet(LIGHT_STYLE)
        self.resize(980,620)
        self.setMinimumSize(720,420)
        self.jobs=[]
        self.source_pixmap=pix.copy()
        layout=QVBoxLayout(self)
        layout.setContentsMargins(18,18,18,16)
        layout.setSpacing(12)
        self.split=QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.preview=OcrImageView(self.source_pixmap)
        self.text=QPlainTextEdit()
        self.text.setAccessibleName('识别文字')
        self.text.setPlaceholderText('正在识别截图中的文字…')
        self.text.setReadOnly(True)
        self.text.setStyleSheet('QPlainTextEdit {background:white;color:#24272c;border:1px solid #dedfe3;border-radius:6px;padding:12px;font-size:14px;selection-background-color:#cfe3ff;}')
        for title,content in [('截图',self.preview),('识别文字',self.text)]:
            pane=QWidget()
            column=QVBoxLayout(pane)
            column.setContentsMargins(0,0,0,0)
            column.setSpacing(8)
            heading=QLabel(title)
            heading.setObjectName('muted')
            column.addWidget(heading)
            column.addWidget(content,1)
            self.split.addWidget(pane)
        self.split.setSizes([460,460])
        layout.addWidget(self.split,1)
        bottom=QHBoxLayout()
        self.status=QLabel('正在本地识别…')
        self.status.setObjectName('muted')
        self.status.setWordWrap(True)
        bottom.addWidget(self.status,1)
        self.copy_button=QPushButton('复制')
        self.copy_button.setObjectName('primary')
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_text)
        bottom.addWidget(self.copy_button)
        self.close_button=QPushButton('关闭')
        self.close_button.clicked.connect(self.close)
        bottom.addWidget(self.close_button)
        layout.addLayout(bottom)
        self.text.textChanged.connect(lambda:self.copy_button.setEnabled(bool(self.text.toPlainText())))
        QTimer.singleShot(0,self.start_recognition)

    def start_recognition(self):
        payload=png_bytes(self.source_pixmap)
        job=Job(lambda:recognize(payload,layout=True))
        self.jobs.append(job)
        job.signals.result.connect(self.recognized)
        job.signals.error.connect(self.failed)
        QThreadPool.globalInstance().start(job)

    def recognized(self,text):
        self.text.setReadOnly(False)
        self.text.setPlaceholderText('识别结果可直接编辑…')
        self.text.setPlainText(text)
        self.status.setText('识别完成，可直接修改文字。' if text.strip() else '未识别到文字，可手动输入。')

    def failed(self,message):
        self.text.setReadOnly(False)
        self.text.setPlaceholderText('可以手动输入文字…')
        self.status.setText('识别失败：'+message[:160])

    def copy_text(self):
        QApplication.clipboard().setText(self.text.toPlainText())
        self.status.setText('已复制')


class InlineTextEdit(QTextEdit):
    def __init__(self,canvas):
        super().__init__(canvas)
        self.canvas=canvas
        self.format_selection=None
        self.frame_drag=None
        self.laying_out=False
        self.composing=False
        self.preedit=''
        self.layout_timer=QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self.relayout)
        self.textChanged.connect(self.schedule_layout)
        self.setAcceptRichText(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        from PySide6.QtGui import QTextOption
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDocumentMargin(4)
        self.setTabChangesFocus(False)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def event(self,event):
        if event.type()==QEvent.Type.ShortcutOverride and event.key() in [Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_Escape]:
            event.accept()
            return True
        if event.type() in (QEvent.Type.MouseMove,QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonRelease):
            if self.frame_mouse(event,event.position().toPoint()):return True
        return super().event(event)

    def schedule_layout(self):
        if not self.laying_out:
            self.layout_timer.start(0)

    def relayout(self):
        if self.canvas.text_editor is self:
            self.canvas.resize_text_editor()

    def inputMethodEvent(self,event):
        self.composing=True
        try:
            super().inputMethodEvent(event)
        finally:
            self.preedit=event.preeditString()
            self.composing=bool(self.preedit)
        self.schedule_layout()

    def viewportEvent(self,event):
        if event.type() in (QEvent.Type.MouseMove,QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonRelease):
            point=self.viewport().mapTo(self,event.position().toPoint())
            if self.frame_mouse(event,point):return True
        return super().viewportEvent(event)

    def frame_mouse(self,event,point):
        inside=self.rect().adjusted(4,4,-4,-4).contains(point)
        if event.type()==QEvent.Type.MouseMove:
            if not event.buttons()&Qt.MouseButton.LeftButton:
                self.frame_drag=None
            cursor=Qt.CursorShape.IBeamCursor if inside and self.frame_drag is None else Qt.CursorShape.SizeAllCursor
            self.setCursor(cursor)
            self.viewport().setCursor(cursor)
            if self.frame_drag is not None:
                start,origin=self.frame_drag
                target=origin+event.globalPosition().toPoint()-start
                x=max(0,min(target.x(),self.canvas.width()-self.width()))
                y=max(0,min(target.y(),self.canvas.height()-self.height()))
                self.anchor=QPoint(x,y)
                self.move(self.anchor)
                return True
        elif event.type()==QEvent.Type.MouseButtonPress and not inside and event.button()==Qt.MouseButton.LeftButton:
            self.frame_drag=(event.globalPosition().toPoint(),self.pos())
            return True
        elif event.type()==QEvent.Type.MouseButtonRelease and self.frame_drag is not None and event.button()==Qt.MouseButton.LeftButton:
            self.frame_drag=None
            return True
        return False
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:
            self.canvas.cancel_text()
            event.accept()
        elif event.key() in [Qt.Key.Key_Enter,Qt.Key.Key_Return] and event.modifiers()&Qt.KeyboardModifier.ControlModifier:
            self.canvas.commit_text()
            event.accept()
        else:
            self.format_selection=None
            super().keyPressEvent(event)

    def focusOutEvent(self,event):
        cursor=self.textCursor()
        if cursor.hasSelection():
            self.format_selection=(cursor.anchor(),cursor.position())
        super().focusOutEvent(event)

    def mousePressEvent(self,event):
        self.format_selection=None
        super().mousePressEvent(event)


@dataclass(frozen=True)
class TextMark:
    text: str
    html: str
    text_width: float
    font: QFont
    position: QPoint
    style: tuple
    raster: QImage
    logical_size: QSize
    scale: float = 1.0

    @classmethod
    def render(cls,document,position,style,scale=1.0):
        from PySide6.QtGui import QAbstractTextDocumentLayout,QPalette
        size=QSize(max(1,math.ceil(min(document.idealWidth(),document.textWidth()))),
                   max(1,math.ceil(document.size().height())))
        # Rasterize once offscreen. Dragging and screen repaints only draw an image.
        density=min(2.0,math.sqrt(8_000_000/(size.width()*size.height())))
        raster=QImage(max(1,math.ceil(size.width()*density)),
                      max(1,math.ceil(size.height()*density)),QImage.Format.Format_ARGB32_Premultiplied)
        raster.fill(Qt.GlobalColor.transparent)
        context=QAbstractTextDocumentLayout.PaintContext()
        palette=QPalette()
        palette.setColor(QPalette.ColorRole.Text,style[4])
        context.palette=palette
        with QPainter(raster) as painter:
            painter.scale(density,density)
            document.documentLayout().draw(painter,context)
        return cls(document.toPlainText(),document.toHtml(),document.textWidth(),
                   QFont(document.defaultFont()),QPoint(position),style,raster,size,scale)

    def create_document(self):
        document=QTextDocument()
        document.setDefaultFont(self.font)
        document.setHtml(self.html)
        document.setTextWidth(self.text_width)
        return document

    def size(self):
        return QSize(max(1,math.ceil(self.logical_size.width()*self.scale)),
                     max(1,math.ceil(self.logical_size.height()*self.scale)))

    def rect(self):
        return QRect(self.position, self.size())


@dataclass(frozen=True)
class NumberMark:
    number: int
    position: QPoint
    color: QColor
    font_size: int

    def radius(self):
        return max(10,round(self.font_size*.8))


class Canvas(QWidget):
    changed = Signal()
    text_selected = Signal(object)

    def __init__(self, pix):
        super().__init__()
        self.image = pix.toImage()
        self.image.setDevicePixelRatio(1)
        self.undo_stack, self.redo_stack = [], []
        self.mode = '箭头'
        self.color = QColor(str(preferences().value('annotation/color','#ff535d')))
        self.pen_width = preferences().value('annotation/arrow_width',8,type=int)
        self.arrow_style='渐细箭头'
        self.line_style=Qt.PenStyle.SolidLine
        self.fill_shape=False
        self.font_size=preferences().value('annotation/font',20,type=int)
        self.block_size=14
        self.mosaic_style='矩形框选'
        self.mosaic_width=32
        self.mosaic_effect=None
        self.font_family='Microsoft YaHei UI'
        self.text_bold=False
        self.text_italic=False
        self.text_editor=None
        self.text_marks=[]
        self.selected_text=None
        self.editing_text=None
        self.text_drag=None
        self.number_marks=[]
        self.selected_number=None
        self.start = self.end = None
        self.stroke = []
        self.setFixedSize(self.image.size())
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.cursor_badge=QLabel(self)
        self.cursor_badge.setFixedSize(22,22)
        self.cursor_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cursor_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.cursor_badge.setStyleSheet('background:rgba(255,255,255,230);border:1px solid #cbd2da;border-radius:4px;')
        self.cursor_badge.hide()

    def pixmap(self):
        self.commit_text()
        image=self.image.copy()
        with QPainter(image) as painter:
            painter.scale(image.width()/self.width(),image.height()/self.height())
            self.paint_number_marks(painter)
            self.paint_text_marks(painter)
        return QPixmap.fromImage(image)

    def text_font(self,scale=1):
        font=QFont(self.font_family)
        font.setPointSizeF(self.font_size*scale)
        font.setBold(self.text_bold)
        font.setItalic(self.text_italic)
        return font

    def text_style(self):
        return self.font_size,self.font_family,self.text_bold,self.text_italic,QColor(self.color)

    def update_text_editor_style(self, apply_format=True):
        if self.text_editor is None:
            if apply_format and self.mode=='文字' and self.selected_text is not None:
                mark=self.text_marks[self.selected_text]
                style=self.text_style()
                if mark.style==style:return
                from PySide6.QtGui import QTextCursor,QTextCharFormat
                document=mark.create_document()
                cursor=QTextCursor(document)
                cursor.select(QTextCursor.SelectionType.Document)
                fmt=QTextCharFormat()
                fmt.setFont(self.text_font(self.width()/self.image.width()))
                fmt.setForeground(self.color)
                cursor.mergeCharFormat(fmt)
                updated=TextMark.render(document,mark.position,style,mark.scale)
                self.snapshot()
                self.text_marks[self.selected_text]=self.fit_text_mark(updated)
                self.update()
            return
        scale=self.width()/self.image.width()
        from PySide6.QtGui import QTextCursor,QTextCharFormat
        editor=self.text_editor
        font=self.text_font(scale)
        c=self.color
        editor.setStyleSheet(f'QTextEdit {{background:transparent;color:rgba({c.red()},{c.green()},{c.blue()},{c.alpha()});font-size:{font.pointSizeF()}pt;border:1px dashed #3286ff;padding:0;selection-background-color:#b5d7ff;}}')
        editor.setFont(font)
        editor.document().setDefaultFont(font)
        cursor=editor.textCursor()
        saved=(cursor.anchor(),cursor.position())
        if not cursor.hasSelection() and editor.format_selection:
            cursor.setPosition(editor.format_selection[0])
            cursor.setPosition(editor.format_selection[1],QTextCursor.MoveMode.KeepAnchor)
        elif not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.Document)
        format=QTextCharFormat()
        format.setFont(font)
        format.setForeground(self.color)
        if apply_format:
            cursor.mergeCharFormat(format)
            editor.mergeCurrentCharFormat(format)
        restore=editor.textCursor()
        restore.setPosition(saved[0])
        restore.setPosition(saved[1],QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(restore)
        if not restore.hasSelection():
            # setHtml restores the saved runs, but leaves the insertion
            # format at the start of the document on the UI theme font.
            editor.setCurrentCharFormat(format)
        self.resize_text_editor()

    def resize_text_editor(self):
        editor=self.text_editor
        if editor is None or editor.laying_out:return
        editor.laying_out=True
        try:
            x,y=editor.anchor.x(),editor.anchor.y()
            document=editor.document()
            border=editor.frameWidth()*2
            measurement=document.clone()
            if editor.preedit:
                from PySide6.QtGui import QTextCursor
                preview=QTextCursor(measurement)
                cursor=editor.textCursor()
                preview.setPosition(cursor.anchor())
                preview.setPosition(cursor.position(),QTextCursor.MoveMode.KeepAnchor)
                preview.insertText(editor.preedit,editor.currentCharFormat())
            measurement.setTextWidth(-1)
            natural_width=max(24,math.ceil(measurement.idealWidth())+border+4)
            editor.setFixedWidth(min(natural_width,self.width()-x))
            measurement.setTextWidth(max(1,editor.width()-border))
            height=math.ceil(measurement.size().height())+border
            if editor.composing:
                # Size the viewport from a detached document. Keep the live
                # composition and its cursor under Qt's input-method control.
                editor.setFixedHeight(min(self.height(),height))
                editor.move(x,max(0,min(y,self.height()-editor.height())))
                return
            document.setTextWidth(max(1,editor.width()-border))
            height=math.ceil(document.size().height())+border
            if height>self.height() and x:
                x=0
                editor.setFixedWidth(self.width())
                document.setTextWidth(max(1,editor.width()-border))
                height=math.ceil(document.size().height())+border
            if height>self.height():
                # Fit the live layout once the input event has returned. A
                # minimum readable font avoids invalid native glyph metrics.
                for _ in range(4):
                    factor=min(0.9,max(0.25,self.height()/height*0.96))
                    if not self.scale_text_document(document,factor,editor.font(),minimum=4):break
                    height=math.ceil(document.size().height())+border
                    if height<=self.height():break
            editor.setFixedHeight(min(self.height(),height))
            editor.move(x,max(0,min(y,self.height()-editor.height())))
            editor.verticalScrollBar().setValue(0)
            editor.horizontalScrollBar().setValue(0)
        finally:
            editor.laying_out=False

    def begin_text(self,pos,index=None):
        self.commit_text()
        self.cursor_badge.hide()
        editor=InlineTextEdit(self)
        self.text_editor=editor
        self.editing_text=index
        self.selected_text=index
        if index is not None:
            pos=self.text_marks[index].position-QPoint(editor.frameWidth(),editor.frameWidth())
        x=max(0,min(pos.x(),self.width()-min(24,self.width())))
        y=max(0,min(pos.y(),self.height()-1))
        editor.anchor=QPoint(x,y)
        if index is not None:
            mark=self.text_marks[index]
            editor.laying_out=True
            try:
                editor.setHtml(mark.html)
                style=mark.style
                if mark.scale!=1:
                    self.scale_text_document(editor.document(),mark.scale,mark.font)
                    style=(max(10,min(96,round(style[0]*mark.scale))),*style[1:])
                self.load_text_style(style)
            finally:
                editor.laying_out=False
        self.update_text_editor_style(apply_format=index is None)
        editor.show()
        editor.raise_()
        editor.setFocus()
        self.update()

    def load_text_style(self,style):
        self.font_size,self.font_family,self.text_bold,self.text_italic,self.color=style
        self.color=QColor(self.color)
        self.text_selected.emit(self.text_style())

    def cancel_text(self):
        editor=self.text_editor
        self.text_editor=None
        self.editing_text=None
        if editor:
            editor.layout_timer.stop()
            editor.frame_drag=None
            editor.hide()
            editor.deleteLater()
            self.setFocus()
        self.update()

    def commit_text(self):
        editor=self.text_editor
        if editor is None:return
        if editor.composing:
            QApplication.inputMethod().commit()
        editor.layout_timer.stop()
        self.resize_text_editor()
        text=editor.toPlainText()
        index=self.editing_text
        if text.strip():
            document=QTextDocument()
            document.setDefaultFont(editor.document().defaultFont())
            document.setHtml(editor.document().toHtml())
            document.setTextWidth(editor.document().textWidth())
            mark=self.fit_text_mark(TextMark.render(document,editor.pos()+QPoint(editor.frameWidth(),editor.frameWidth()),self.text_style()))
            self.snapshot()
            if index is None:
                index=len(self.text_marks)
                self.text_marks.append(mark)
            else:self.text_marks[index]=mark
            self.selected_text=index
        self.cancel_text()

    def fit_text_mark(self,mark):
        size=mark.size()
        factor=min(1,self.width()/size.width(),self.height()/size.height())
        if factor<1:mark=replace(mark,scale=mark.scale*factor)
        size=mark.size()
        point=QPoint(max(0,min(mark.position.x(),self.width()-size.width())),
                     max(0,min(mark.position.y(),self.height()-size.height())))
        return replace(mark,position=point)

    def paint_text_marks(self,painter):
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for index,mark in enumerate(self.text_marks):
            if index==self.editing_text:continue
            painter.drawImage(mark.rect(),mark.raster)

    @staticmethod
    def scale_text_document(document,scale,default_font,minimum=4):
        from PySide6.QtGui import QTextCursor,QTextCharFormat
        fragments=[]
        block=document.begin()
        while block.isValid():
            iterator=block.begin()
            while not iterator.atEnd():
                fragment=iterator.fragment()
                if fragment.isValid():
                    size=fragment.charFormat().fontPointSize() or default_font.pointSizeF()
                    target=max(minimum,size*scale)
                    if abs(size-target)>0.01:
                        fragments.append((fragment.position(),fragment.length(),target))
                iterator+=1
            block=block.next()
        cursor=QTextCursor(document)
        for position,length,size in fragments:
            cursor.setPosition(position)
            cursor.setPosition(position+length,QTextCursor.MoveMode.KeepAnchor)
            fmt=QTextCharFormat()
            fmt.setFontPointSize(size)
            cursor.mergeCharFormat(fmt)
        return bool(fragments)

    def text_at(self,pos):
        for index in range(len(self.text_marks)-1,-1,-1):
            if self.text_marks[index].rect().adjusted(-3,-3,3,3).contains(pos):return index
        return None

    def text_handle(self):
        if self.selected_text is None:return QRect()
        end=self.text_marks[self.selected_text].rect().bottomRight()
        point=QPoint(max(0,min(end.x()-6,self.width()-15)),max(0,min(end.y()-6,self.height()-15)))
        return QRect(point,QSize(12,12))

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Delete and self.mode=='序号' and self.delete_number():
            event.accept()
            return
        if self.mode=='文字' and self.selected_text is not None:
            if event.key()==Qt.Key.Key_F2:
                self.edit_text(self.selected_text)
                event.accept()
                return
            if event.matches(QKeySequence.StandardKey.SelectAll):
                index=self.selected_text
                self.begin_text(self.text_marks[index].position,index)
                self.text_editor.selectAll()
                return
            if event.key()==Qt.Key.Key_Delete:
                self.snapshot()
                del self.text_marks[self.selected_text]
                self.selected_text=None
                self.update()
                return
        super().keyPressEvent(event)

    def snapshot(self):
        self.undo_stack.append(self.annotation_state())
        if len(self.undo_stack) > 15:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def annotation_state(self):
        return self.image.copy(),self.text_marks.copy(),self.number_marks.copy()

    def undo(self):
        self.cancel_text()
        self.text_drag=None
        if self.undo_stack:
            self.redo_stack.append(self.annotation_state())
            self.image,self.text_marks,self.number_marks = self.undo_stack.pop()
            self.selected_text=None
            self.selected_number=None
            self.update()

    def redo(self):
        self.cancel_text()
        self.text_drag=None
        if self.redo_stack:
            self.undo_stack.append(self.annotation_state())
            self.image,self.text_marks,self.number_marks = self.redo_stack.pop()
            self.selected_text=None
            self.selected_number=None
            self.update()

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.save()
            try:
                painter.scale(self.width()/self.image.width(), self.height()/self.image.height())
                painter.drawImage(0,0,self.image)
                if self.start is not None:self.draw(painter)
            finally:
                painter.restore()
            self.paint_number_marks(painter)
            self.paint_text_marks(painter)
            if self.mode=='序号' and self.selected_number is not None:
                mark=self.number_marks[self.selected_number]
                painter.setPen(QPen(QColor('#3286ff'),1.5,Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                radius=mark.radius()+3
                painter.drawEllipse(mark.position,radius,radius)
            if self.mode=='文字' and self.selected_text is not None and self.text_editor is None:
                painter.setPen(QPen(QColor('#3286ff'),1,Qt.PenStyle.DashLine))
                painter.drawRect(self.text_marks[self.selected_text].rect())
                painter.fillRect(self.text_handle().adjusted(3,3,-3,-3),QColor('#3286ff'))

    def paint_number_marks(self,painter):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for mark in self.number_marks:
            radius=mark.radius()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(mark.color)
            painter.drawEllipse(mark.position,radius,radius)
            painter.setPen(QColor('white'))
            painter.setFont(QFont('Arial',mark.font_size,QFont.Weight.Bold))
            rect=QRect(mark.position-QPoint(radius,radius),QSize(radius*2,radius*2))
            painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,str(mark.number))
        painter.restore()

    def number_at(self,point):
        for index in range(len(self.number_marks)-1,-1,-1):
            mark=self.number_marks[index]
            delta=point-mark.position
            if delta.x()**2+delta.y()**2<=(mark.radius()+2)**2:return index
        return None

    def delete_number(self):
        if self.selected_number is None:return False
        self.snapshot()
        del self.number_marks[self.selected_number]
        self.selected_number=None
        self.update()
        return True

    def draw(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self.color, self.pen_width, self.line_style, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(self.color if self.fill_shape else Qt.BrushStyle.NoBrush)
        if self.fill_shape and self.mode in ['矩形','圆角矩形','椭圆']:
            p.setPen(Qt.PenStyle.NoPen)
        r = QRect(self.start, self.end).normalized()
        if self.mode == '矩形':
            p.drawRect(r)
        elif self.mode=='圆角矩形':
            p.drawRoundedRect(r,min(18,r.width()/5),min(18,r.height()/5))
        elif self.mode == '椭圆':
            p.drawEllipse(r)
        elif self.mode in ['画笔','荧光笔']:
            if self.mode=='荧光笔':
                col=QColor(self.color)
                col.setAlpha(round(self.color.alpha()*.31))
                p.setPen(QPen(col,max(14,self.pen_width*5),Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
            for a, b in zip(self.stroke, self.stroke[1:]):
                p.drawLine(a, b)
        elif self.mode == '箭头':
            draw_arrow(p,self.start,self.end,self.color,self.pen_width,self.arrow_style,self.line_style)
        elif self.mode == '马赛克':
            if self.mosaic_effect is None:self.mosaic_effect=MosaicEffect(self.image)
            self.mosaic_effect.draw(p,self.start,self.end,self.stroke,self.mosaic_style,self.mosaic_width,self.block_size)

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = self.image_pos(e.position().toPoint())
        if self.mode!='文字':self.commit_text()
        if self.mode=='序号':
            point=e.position().toPoint()
            self.selected_number=self.number_at(point)
            if self.selected_number is None:
                used={mark.number for mark in self.number_marks}
                number=next(value for value in range(1,len(used)+2) if value not in used)
                self.snapshot()
                self.number_marks.append(NumberMark(number,point,QColor(self.color),self.font_size))
                self.selected_number=len(self.number_marks)-1
            self.setFocus()
            self.update()
            return
        if self.mode == '文字':
            point=e.position().toPoint()
            was_editing=self.text_editor is not None
            if was_editing:
                self.commit_text()
            resize=self.text_handle().contains(point)
            index=self.selected_text if resize else self.text_at(point)
            if index is None:
                if not was_editing:self.begin_text(point)
                return
            self.selected_text=index
            mark=self.text_marks[index]
            self.load_text_style(mark.style)
            self.text_drag=(point,mark,resize)
            self.setFocus()
            self.update()
            return
        self.start = self.end = pos
        self.stroke = [pos]
        if self.mode=='马赛克':self.mosaic_effect=MosaicEffect(self.image)

    def mouseMoveEvent(self, e):
        point=e.position().toPoint()
        if self.text_drag is not None:
            origin,mark,resize=self.text_drag
            delta=point-origin
            if resize:
                size=mark.size()
                factor=1+(delta.x()*size.width()+delta.y()*size.height())/(size.width()**2+size.height()**2)
                changed=replace(mark,scale=max(0.15,mark.scale*factor))
            else:changed=replace(mark,position=mark.position+delta)
            self.text_marks[self.selected_text]=self.fit_text_mark(changed)
            self.cursor_badge.hide()
            self.update()
            return
        if self.mode=='文字' and (self.text_handle().contains(point) or self.text_at(point) is not None):
            if self.property('edge_hover'):return
            self.cursor_badge.hide()
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if self.text_handle().contains(point) else Qt.CursorShape.SizeAllCursor)
            return
        if self.mode=='文字' and not self.property('edge_hover'):self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update_badge(point)
        if self.start is not None:
            self.end = self.image_pos(e.position().toPoint())
            self.stroke.append(self.end)
            self.update()

    def update_badge(self,pos):
        if self.mode=='选区' or self.property('edge_hover'):
            self.cursor_badge.hide()
            return
        self.cursor_badge.setPixmap(badge_icon(self.mode,self.color))
        self.cursor_badge.move(pos+QPoint(15,18))
        self.cursor_badge.show()
        self.cursor_badge.raise_()

    def leaveEvent(self,event):
        self.cursor_badge.hide()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, e):
        if self.text_drag is not None and e.button()==Qt.MouseButton.LeftButton:
            _,original,_=self.text_drag
            self.text_drag=None
            updated=self.text_marks[self.selected_text]
            if updated!=original:
                self.text_marks[self.selected_text]=original
                self.snapshot()
                self.text_marks[self.selected_text]=updated
            self.update()
            return
        if self.start is not None:
            self.end = self.image_pos(e.position().toPoint())
            self.stroke.append(self.end)
            self.snapshot()
            # Mosaic preview and commit share the immutable source captured on press.
            p = QPainter(self.image)
            self.draw(p)
            p.end()
            self.start = self.end = None
            self.mosaic_effect=None
            self.update()

    def mouseDoubleClickEvent(self,event):
        if self.mode=='文字' and event.button()==Qt.MouseButton.LeftButton:
            if self.edit_text_at(event.position().toPoint()):
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def edit_text_at(self,point):
        index=self.text_at(point)
        if index is None:return False
        return self.edit_text(index)

    def edit_text(self,index):
        if not 0<=index<len(self.text_marks):return False
        self.text_drag=None
        self.begin_text(self.text_marks[index].position,index)
        return True

    def image_pos(self,pos):
        return QPoint(round(pos.x()*self.image.width()/self.width()),round(pos.y()*self.image.height()/self.height()))


class Pin(QLabel):
    def __init__(self, pix, controller=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.original = pix
        self.controller=controller
        self.closed_by_user=False
        self.original.setDevicePixelRatio(1)
        self.scale = min(1.0, 700/max(pix.width(),pix.height()))
        self.offset = None
        self.setWindowOpacity(preferences().value('pin/opacity',100,type=int)/100)
        self.refresh()
        self.setToolTip('拖动移动 · 滚轮缩放 · 双击关闭 · 右键菜单')
        self.show()

    def refresh(self):
        scaled = self.original.scaled(self.original.size()*self.scale, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(scaled)
        self.resize(scaled.size())

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self.offset is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint()-self.offset)

    def mouseReleaseEvent(self, e):
        self.offset = None

    def mouseDoubleClickEvent(self, e):
        if str(preferences().value('pin/double','关闭'))=='恢复原始大小':
            self.scale=1
            self.refresh()
        else:self.close()

    def wheelEvent(self, e):
        self.scale = min(4, max(0.1, self.scale*(1.1 if e.angleDelta().y()>0 else 1/1.1)))
        self.refresh()

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.addAction('复制图片', lambda: QApplication.clipboard().setPixmap(self.original))
        menu.addAction(lucide('scan-letter-a'),'文字识别',self.open_text)
        menu.addAction(lucide('languages'),'翻译',self.open_translation)
        menu.addAction('水平翻转',lambda:self.flip(True))
        menu.addAction('垂直翻转',lambda:self.flip(False))
        menu.addAction('恢复原始大小',self.original_size)
        menu.addSeparator()
        menu.addAction('透明度 60%', lambda: self.setWindowOpacity(0.6))
        menu.addAction('透明度 100%', lambda: self.setWindowOpacity(1))
        menu.addAction('保存图片',self.save)
        menu.addAction('关闭', self.close)
        menu.exec(e.globalPos())

    def original_size(self):
        self.scale=1
        self.refresh()

    def flip(self,horizontal):
        self.original=QPixmap.fromImage(self.original.toImage().mirrored(horizontal,not horizontal))
        self.refresh()

    def save(self):
        path=choose_save_path(self,'保存贴图','轻截贴图')
        if path:
            if self.original.save(path,'PNG'):remember_saved_file(path)
            else:QMessageBox.warning(self,'保存失败','无法写入图片。')

    def closeEvent(self,event):
        self.closed_by_user=True
        if self.controller:self.controller.last_pin=self.original.copy()
        event.accept()

    def open_text(self):
        self.text_dialog = OcrDialog(self.original, self)
        self.text_dialog.show()

    def open_translation(self):
        from translation_popup import TranslationPopup
        popup=TranslationPopup(self.original,self.geometry())
        self.translation_popup=popup
        popup.start()


class Editor(QMainWindow):
    def __init__(self, pix, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle('轻截 · 截图编辑')
        self.setWindowIcon(icon())
        self.canvas = Canvas(pix)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(scroll)
        bar = QToolBar()
        self.addToolBar(bar)
        self.tools = []
        for mode in ['箭头','矩形','圆角矩形','椭圆','画笔','荧光笔','马赛克','文字','序号']:
            act = bar.addAction(mode)
            act.setCheckable(True)
            act.setChecked(mode == self.canvas.mode)
            act.triggered.connect(lambda _, m=mode: self.select(m))
            self.tools.append(act)
        bar.addSeparator()
        bar.addAction('撤销', self.canvas.undo)
        bar.addAction('重做', self.canvas.redo)
        second = QToolBar()
        self.addToolBarBreak()
        self.addToolBar(second)
        second.addAction('复制  Enter', self.copy)
        second.addAction('另存为  Ctrl+S', self.save)
        second.addAction('置顶贴图', self.pin)
        second.addAction(lucide('scan-letter-a'),'文字识别',self.text)
        second.addAction(lucide('languages'),'翻译',self.translation)
        self.options=AnnotationOptions(self)
        self.canvas.text_selected.connect(self.options.load_text_style)
        options_bar=QToolBar()
        self.addToolBarBreak()
        self.addToolBar(options_bar)
        options_bar.addWidget(self.options)
        self.options.show()
        self.options.set_mode(self.canvas.mode)
        QShortcut(QKeySequence('Ctrl+Z'), self, self.canvas.undo)
        QShortcut(QKeySequence('Ctrl+Y'), self, self.canvas.redo)
        QShortcut(QKeySequence('Ctrl+S'), self, self.save)
        QShortcut(QKeySequence('Ctrl+C'), self, self.copy)
        QShortcut(QKeySequence('Return'), self, self.copy)
        self.statusBar().showMessage(f'{pix.width()} × {pix.height()} · 本地编辑 · OCR 不联网')
        self.resize(1100,760)

    def select(self, mode):
        if self.canvas.mode=='文字' and mode!='文字':
            self.canvas.commit_text()
            self.canvas.selected_text=None
            self.canvas.text_drag=None
        self.canvas.mode = mode
        if hasattr(self,'options'):self.options.set_mode(mode)
        for act in self.tools:
            act.setChecked(act.text()==mode)

    def tool(self,mode):self.select(mode)

    def color(self):
        color = QColorDialog.getColor(self.canvas.color, self)
        if color.isValid():
            self.canvas.color = color

    def copy(self):
        QApplication.clipboard().setPixmap(self.canvas.pixmap())
        self.statusBar().showMessage('已复制图片到剪贴板')

    def save(self):
        path=choose_save_path(self,'保存截图')
        if path:
            if self.canvas.pixmap().save(path,'PNG'):remember_saved_file(path)
            else:QMessageBox.warning(self,'保存失败','无法写入该路径。')

    def pin(self):
        self.controller.pin(self.canvas.pixmap())

    def text(self):
        self.dialog = OcrDialog(self.canvas.pixmap(), self)
        self.dialog.show()

    def translation(self):
        from translation_popup import TranslationPopup
        self.translation_popup=TranslationPopup(self.canvas.pixmap(),self.geometry())
        self.translation_popup.start()


class BasicOverlay(QWidget):
    selected = Signal(object)
    cancelled = Signal()

    def __init__(self, screen, frozen):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.frozen, self.screen_ref = frozen, screen
        self.start = self.end = None
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, e):
        with QPainter(self) as p:
            p.drawPixmap(self.rect(),self.frozen)
            p.fillRect(self.rect(), QColor(0,0,0,110))
            if self.start is not None:
                r = QRect(self.start,self.end).normalized().intersected(self.rect())
                p.save()
                p.setClipRect(r)
                p.drawPixmap(self.rect(),self.frozen)
                p.restore()
                p.setPen(QPen(QColor('#55dfbd'),2))
                p.drawRect(r)
                p.drawText(r.topLeft()+QPoint(5,-8),f'{r.width()} × {r.height()}')
            else:
                p.setPen(QColor('white'))
                p.drawText(28,42,'轻截  ·  拖动框选截图区域，松开进入编辑；Esc 取消')

    def mousePressEvent(self, e):
        if e.button()==Qt.MouseButton.RightButton:
            self.cancelled.emit()
        elif e.button()==Qt.MouseButton.LeftButton:
            self.start=self.end=e.position().toPoint()

    def mouseMoveEvent(self,e):
        if self.start is not None:
            self.end=e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self,e):
        if e.button()!=Qt.MouseButton.LeftButton or self.start is None:
            return
        r=QRect(self.start,e.position().toPoint()).normalized().intersected(self.rect())
        if r.width()<3 or r.height()<3:
            self.cancelled.emit()
            return
        sx,sy=self.frozen.width()/self.width(),self.frozen.height()/self.height()
        pix=self.frozen.copy(QRect(round(r.x()*sx),round(r.y()*sy),round(r.width()*sx),round(r.height()*sy)))
        pix.setDevicePixelRatio(1)
        self.selected.emit(pix)

    def keyPressEvent(self,e):
        if e.key()==Qt.Key.Key_Escape:
            self.cancelled.emit()


class Overlay(BasicOverlay):
    def __init__(self,screen,frozen,controller=None,window_catalog=None):
        super().__init__(screen,frozen)
        self.controller=controller
        self.setWindowTitle('轻截 · 截图')
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.active_screen=(controller is None or screen.geometry().contains(QCursor.pos()))
        self.rect_selected=None
        self.canvas=None
        self.window_catalog=window_catalog
        self.window_detection=flag('capture/window_detection',True)
        self.hover_target=None
        self._pressed_target=None
        self.manual_drag=False
        self.preview_level=0
        self.preview_anchor=None
        self.detect_elements=True
        self.drag_kind=None
        self.cursor_pos=QPoint(80,80)
        self.mode='选区'
        self.actions={}
        self.bar=QToolBar(self)
        self.bar.setStyleSheet(TOOLBAR_STYLE)
        self.bar.setIconSize(QSize(20,20))
        self.bar.setMovable(False)
        self.bar.addAction(lucide('grip-vertical','#000000',14),'移动选区',lambda:self.tool('选区'))
        from PySide6.QtWidgets import QToolButton
        def group(items):
            name,svg=items[0]
            button=QToolButton()
            button.setIconSize(QSize(20,20))
            button.setIcon(lucide(svg))
            button.setToolTip(name)
            button.setCheckable(True)
            button.clicked.connect(lambda:self.tool(button.property('mode') or name))
            button.setProperty('mode',name)
            self.actions[name]=button
            self.bar.addWidget(button)
        group([('矩形','square'),('圆角矩形','square'),('椭圆','circle')])
        group([('画笔','pencil'),('荧光笔','highlighter')])
        group([('箭头','annotation-arrow')])
        group([('文字','type')])
        group([('序号','list-ordered')])
        group([('马赛克','pixel-mosaic')])
        self.bar.addAction(lucide('eraser'),'清除所有标注 Ctrl+Shift+Z',self.clear_marks)
        self.bar.addSeparator()
        for svg,tip,fn in [('scroll-capture','滚动长截图 L',lambda:self.session('scroll')),('video','静音录屏 G',lambda:self.session('video')),('scan-letter-a','文字识别 Shift+C',self.ocr),('languages','翻译（联网发送文字）',self.translate_popup),('pin','贴图 Ctrl+T',self.pin),('download','保存',self.save),('x','取消 Esc',lambda:self.cancelled.emit()),('copy','复制 Enter / Ctrl+C',self.finish)]:
            a=self.bar.addAction(lucide(svg),tip)
            a.setToolTip(tip)
            a.triggered.connect(fn)
        more=QMenu(self.bar)
        more.addAction(lucide('undo-2'),'撤销 Ctrl+Z',lambda:self.canvas.undo())
        more.addAction(lucide('redo-2'),'重做 Ctrl+Y',lambda:self.canvas.redo())
        more.addAction(lucide('move'),'移动选区 V',lambda:self.tool('选区'))
        morebutton=QToolButton()
        morebutton.setIconSize(QSize(20,20))
        morebutton.setIcon(lucide('ellipsis'))
        morebutton.setMenu(more)
        morebutton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.bar.addWidget(morebutton)
        self.bar.hide()
        self.bar.setCursor(Qt.CursorShape.ArrowCursor)
        self.options=AnnotationOptions(self)
        self.border=SelectionBorder(self)
        self.hints=QFrame(self)
        self.hints.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hints.setCursor(Qt.CursorShape.ArrowCursor)
        self.hints.setStyleSheet('QFrame {background:rgba(20,22,25,225);border:0;border-radius:5px;} QLabel {color:white;background:transparent;font-size:12px;} QLabel#key {background:#f2f3f5;color:#1b1e22;border-radius:4px;padding:3px 6px;font-weight:600;}')
        hint_layout=QGridLayout(self.hints)
        hint_layout.setContentsMargins(12,12,12,12)
        hint_layout.setHorizontalSpacing(12)
        hint_layout.setVerticalSpacing(8)
        for row,(key,label) in enumerate([('L','滚动长截图'),('G','录制视频'),('Shift+C','识别选区文字'),('Ctrl+T','置顶贴图'),('Ctrl+Shift+Z','清除所有标注'),('Enter / Ctrl+C','复制截图'),('Esc','取消截图')]):
            key_label=QLabel(key)
            key_label.setObjectName('key')
            key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint_layout.addWidget(key_label,row,0)
            hint_layout.addWidget(QLabel(label),row,1)
        self.detection_hint_key=QLabel()
        self.detection_hint_key.setObjectName('key')
        self.detection_hint_key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detection_hint_state=QLabel()
        hint_layout.addWidget(self.detection_hint_key,7,0)
        hint_layout.addWidget(self.detection_hint_state,7,1)
        for row,key,label in [(8,'鼠标滚轮','选择上层 / 下层元素'),(9,'Tab','切换整窗 / 内部元素')]:
            shortcut=QLabel(key)
            shortcut.setObjectName('key')
            shortcut.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint_layout.addWidget(shortcut,row,0)
            hint_layout.addWidget(QLabel(label),row,1)
        self.refresh_detection_hint()
        self.hints.adjustSize()
        self.position_hints()
        # Tool widgets and inline text editors can consume Ctrl+C before the
        # overlay's keyPressEvent. Capture it throughout this screenshot window.
        QApplication.instance().installEventFilter(self)

    def position_hints(self):
        if not hasattr(self,'hints'):return
        selection=self.copy_source()
        show_here=self is selection if selection is not None else self.active_screen
        protected=[QRect(self.cursor_pos-QPoint(24,24),QSize(49,49))]
        if self.rect_selected is not None:protected.append(self.rect_selected.adjusted(-8,-8,8,8))
        elif self.start is not None and self.end is not None:
            protected.append(QRect(self.start,self.end).normalized().adjusted(-8,-8,8,8))
        for widget in [self.bar,self.options]:
            if not widget.isHidden():protected.append(widget.geometry().adjusted(-4,-4,4,4))
        w,h=self.hints.width(),self.hints.height()
        corners=[QPoint(18,self.height()-h-18),QPoint(18,18),
                 QPoint(self.width()-w-18,self.height()-h-18),QPoint(self.width()-w-18,18)]
        def fits(point):
            rect=QRect(point,QSize(w,h))
            return self.rect().contains(rect) and not any(rect.intersects(item) for item in protected)
        # Keep a safe corner stable while dragging, rather than chasing the mouse.
        current=self.hints.pos()
        point=current if current in corners and fits(current) else next((p for p in corners if fits(p)),None)
        if point is not None:self.hints.move(point)
        self.hints.setVisible(show_here and point is not None and flag('capture/hints',True))
        self.hints.raise_()

    def set_capture_active(self,active,cursor_pos):
        changed=self.active_screen!=active
        self.active_screen=active
        if active:self.cursor_pos=cursor_pos-self.geometry().topLeft()
        self.update_window_preview()
        self.position_hints()
        if changed or (active and self.rect_selected is None):self.update()

    def refresh_detection_hint(self):
        self.detection_hint_key.setText(keys().get(8,'F8') or '未设置')
        self.detection_hint_state.setText('窗口边界识别：'+('开' if self.window_detection else '关'))

    def set_window_detection(self,enabled):
        self.window_detection=bool(enabled)
        if not enabled:self.hover_target=None
        self.refresh_detection_hint()
        self.hints.adjustSize()
        self.update_window_preview()
        self.position_hints()
        self.update()

    def toggle_window_detection(self):
        callback=getattr(self.controller,'toggle_window_detection',None)
        if callable(callback):callback()
        else:self.set_window_detection(not self.window_detection)

    def window_target_at(self,pos):
        if not self.window_detection or self.window_catalog is None:return None
        point=pos+self.geometry().topLeft()
        candidates=self.window_catalog.candidates_at(point,self.screen_ref)
        if not candidates:return None
        scanner=getattr(self.controller,'region_scanner',None)
        if scanner is not None:scanner.ensure(candidates[-1],self.frozen)
        return candidates[min(self.preview_level,len(candidates)-1)] if self.detect_elements else candidates[-1]

    def update_window_preview(self):
        if not self.active_screen or not self.window_detection or self.copy_source() is not None:
            self.hover_target=None
        elif self.start is None:
            if self.preview_anchor is None or (self.cursor_pos-self.preview_anchor).manhattanLength()>6:
                self.preview_level=0
                self.preview_anchor=QPoint(self.cursor_pos)
            self.hover_target=self.window_target_at(self.cursor_pos)

    def wheelEvent(self,event):
        if self.rect_selected is None and self.start is None and self.window_detection and self.window_catalog is not None:
            self.cursor_pos=event.position().toPoint()
            candidates=self.window_catalog.candidates_at(self.mapToGlobal(self.cursor_pos),self.screen_ref)
            if candidates:
                self.detect_elements=True
                delta=event.angleDelta().y()
                self.preview_level=max(0,min(len(candidates)-1,self.preview_level+(1 if delta>0 else -1 if delta<0 else 0)))
                self.preview_anchor=QPoint(self.cursor_pos)
                self.hover_target=candidates[self.preview_level]
                self.update()
            event.accept()
        else:super().wheelEvent(event)

    def target_rect(self,target):
        return target.logical.translated(-self.geometry().x(),-self.geometry().y()).intersected(self.rect())

    def crop_target(self,target):
        pix=self.frozen.copy(target.mapping.frozen_rect(target.native,self.frozen.size()))
        pix.setDevicePixelRatio(1)
        return pix

    def is_detection_toggle(self,event):
        shortcut=keys().get(8,'F8')
        return bool(shortcut) and QKeySequence(event.keyCombination())==QKeySequence(shortcut)

    def detection_toggle_is_native(self):
        hotkeys=getattr(self.controller,'hotkeys',None)
        return hotkeys is not None and 101 in hotkeys.registered

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.position_hints()
        if hasattr(self,'border'):self.border.setGeometry(self.rect())

    def paintEvent(self,event):
        with QPainter(self) as p:
            p.drawPixmap(self.rect(),self.frozen)
            p.fillRect(self.rect(),QColor(0,0,0,105))
            r=self.rect_selected
            if r is None and self.start is not None and (self.manual_drag or self.hover_target is None):
                r=QRect(self.start,self.end).normalized().intersected(self.rect())
            if r is None and self.hover_target is not None:r=self.target_rect(self.hover_target)
            if r:
                if not self.canvas or self.canvas.isHidden():
                    p.save()
                    p.setClipRect(r)
                    p.drawPixmap(self.rect(),self.frozen)
                    p.restore()
                p.setPen(QPen(QColor('#3286ff'),BORDER_WIDTH))
                p.drawRect(r)
                if self.mode=='选区' and self.rect_selected is not None:
                    p.setBrush(QColor('white'))
                    for pt in self.handles(r):p.drawEllipse(pt,4,4)
                if flag('capture/guides',False):
                    p.setPen(QPen(QColor('#7bb4ff'),1,Qt.PenStyle.DashLine))
                    p.drawLine(r.center().x(),r.top(),r.center().x(),r.bottom())
                    p.drawLine(r.left(),r.center().y(),r.right(),r.center().y())
                if flag('capture/info',True):
                    sx=self.frozen.width()/self.width()
                    sy=self.frozen.height()/self.height()
                    label=f'{r.x()},{r.y()}  {round(r.width()*sx)} × {round(r.height()*sy)} px'
                    box=QRect(r.left(),max(0,r.top()-29),max(170,len(label)*7),24)
                    p.setPen(QPen(QColor('#dadde3'),1))
                    p.setBrush(QColor(40,40,40,210))
                    p.drawRoundedRect(box,12,12)
                    p.setPen(QColor('white'))
                    p.drawText(box,Qt.AlignmentFlag.AlignCenter,label)
            elif self.active_screen and flag('capture/magnifier',True):
                sx,sy=self.frozen.width()/self.width(),self.frozen.height()/self.height()
                pos=self.cursor_pos
                sample=self.frozen.copy(QRect(round(pos.x()*sx)-6,round(pos.y()*sy)-6,13,13))
                box=QRect(min(pos.x()+24,self.width()-170),min(pos.y()+24,self.height()-195),156,156)
                p.drawPixmap(box,sample)
                p.setPen(QPen(QColor('#3286f5'),1))
                p.drawRect(box)
                p.drawRect(QRect(box.center()-QPoint(6,6),QSize(12,12)))
                p.fillRect(QRect(box.left(),box.bottom(),156,28),QColor(0,0,0,190))
                p.setPen(QColor('white'))
                p.drawText(box.left()+8,box.bottom()+19,f'({pos.x()}, {pos.y()})')

    def handles(self,r):
        return [r.topLeft(),QPoint(r.center().x(),r.top()),r.topRight(),QPoint(r.right(),r.center().y()),r.bottomRight(),QPoint(r.center().x(),r.bottom()),r.bottomLeft(),QPoint(r.left(),r.center().y())]

    def crop(self,r):
        sx,sy=self.frozen.width()/self.width(),self.frozen.height()/self.height()
        pix=self.frozen.copy(QRect(round(r.x()*sx),round(r.y()*sy),round(r.width()*sx),round(r.height()*sy)))
        pix.setDevicePixelRatio(1)
        return pix

    def set_selection(self,r,window_target=None,keep_text=False):
        r=r.normalized().intersected(self.rect())
        if r.width()<3 or r.height()<3:return
        self.rect_selected=r
        self.hover_target=None
        marks=[]
        numbers=[]
        if self.canvas:
            if keep_text:
                self.canvas.commit_text()
                offset=self.canvas.pos()-r.topLeft()
                marks=[replace(mark,position=mark.position+offset) for mark in self.canvas.text_marks]
                for mark in self.canvas.number_marks:
                    point=mark.position+offset
                    point=QPoint(max(0,min(point.x(),r.width()-1)),max(0,min(point.y(),r.height()-1)))
                    numbers.append(replace(mark,position=point))
            self.canvas.hide()
            self.canvas.deleteLater()
        self.canvas=Canvas(self.crop_target(window_target) if window_target is not None else self.crop(r))
        self.canvas.text_selected.connect(self.options.load_text_style)
        self.canvas.setParent(self)
        self.canvas.installEventFilter(self)
        self.canvas.setFixedSize(r.size())
        self.canvas.text_marks=[self.canvas.fit_text_mark(mark) for mark in marks]
        self.canvas.number_marks=numbers
        self.canvas.move(r.topLeft())
        self.canvas.show()
        if self.controller is not None:self.controller.current_capture=self
        self.position_hints()
        self.tool('选区')
        self.layout_bars()
        self.update()

    def layout_bars(self):
        self.bar.adjustSize()
        self.options.adjustSize()
        r=self.rect_selected
        x=max(0,min(r.right()-self.bar.sizeHint().width()+1,self.width()-self.bar.sizeHint().width()))
        y=r.bottom()+9
        if y+self.bar.sizeHint().height()+self.options.sizeHint().height()+8>self.height():
            y=max(0,r.top()-self.bar.sizeHint().height()-self.options.sizeHint().height()-12)
        self.bar.move(x,y)
        self.bar.show()
        self.bar.raise_()
        self.options.move(max(0,min(x,self.width()-self.options.sizeHint().width())),y+self.bar.height()+4)
        if self.mode!='选区':self.options.show()
        self.options.raise_()
        self.border.setGeometry(self.rect())
        self.border.setVisible(self.rect_selected is not None)
        self.border.raise_()
        self.border.update()
        self.bar.raise_()
        self.options.raise_()
        self.position_hints()

    def tool(self,mode):
        if self.canvas and self.canvas.mode=='文字' and mode!='文字':
            self.canvas.commit_text()
            self.canvas.selected_text=None
            self.canvas.text_drag=None
        self.mode=mode
        for modes,svg in [(['矩形','圆角矩形','椭圆'],'square'),(['画笔','荧光笔'],'pencil')]:
            if mode in modes:
                button=self.actions[modes[0]]
                button.setProperty('mode',mode)
                button.setToolTip(mode)
                button.setIcon(lucide('circle' if mode=='椭圆' else 'highlighter' if mode=='荧光笔' else svg))
        for name,a in self.actions.items():a.setChecked((a.property('mode') or name)==mode)
        if self.canvas:
            self.canvas.mode=mode
            self.canvas.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,mode=='选区')
            self.options.set_mode(mode)
            self.canvas.setCursor(tool_cursor(mode,self.canvas.color))
        self.setCursor(Qt.CursorShape.ArrowCursor if mode=='选区' else tool_cursor(mode,QColor('#202020')))
        self.options.setVisible(mode!='选区' and self.canvas is not None)
        self.setFocus()
        self.update()
        if self.canvas:self.layout_bars()

    def edge_at(self,pos):
        r=self.rect_selected
        half=BORDER_WIDTH//2
        if r is None or not r.adjusted(-half,-half,half,half).contains(pos):return None
        left,right=abs(pos.x()-r.left())<=half,abs(pos.x()-r.right())<=half
        top,bottom=abs(pos.y()-r.top())<=half,abs(pos.y()-r.bottom())<=half
        if left and top:return 0
        if right and top:return 2
        if right and bottom:return 4
        if left and bottom:return 6
        if top:return 1
        if right:return 3
        if bottom:return 5
        if left:return 7
        return None

    def edge_cursor(self,index):
        return [Qt.CursorShape.SizeFDiagCursor,Qt.CursorShape.SizeVerCursor,Qt.CursorShape.SizeBDiagCursor,Qt.CursorShape.SizeHorCursor,Qt.CursorShape.SizeFDiagCursor,Qt.CursorShape.SizeVerCursor,Qt.CursorShape.SizeBDiagCursor,Qt.CursorShape.SizeHorCursor][index]

    def update_pointer(self,pos):
        edge=self.edge_at(pos)
        cursor=self.edge_cursor(edge) if edge is not None else Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)
        if self.canvas:
            self.canvas.setCursor(cursor)
            self.canvas.setProperty('edge_hover',edge is not None)
            if edge is not None:self.canvas.cursor_badge.hide()

    def recover_released_drag(self):
        if self.drag_kind is None:return
        self.drag_kind=None
        if self.canvas and self.canvas.isHidden():
            mode=self.mode
            r=self.rect_selected
            self.set_selection(r,keep_text=True)
            self.tool(mode)
        elif self.canvas:self.layout_bars()

    def eventFilter(self,watched,event):
        if event.type() in [QEvent.Type.ShortcutOverride,QEvent.Type.KeyPress] and self.isVisible() and isinstance(watched,QWidget) and (watched is self or self.isAncestorOf(watched)):
            if self.is_detection_toggle(event):
                event.accept()
                if event.type()==QEvent.Type.KeyPress and not event.isAutoRepeat() and not self.detection_toggle_is_native():self.toggle_window_detection()
                return True
            if event.key()==Qt.Key.Key_Tab and self.rect_selected is None:
                event.accept()
                if event.type()==QEvent.Type.KeyPress and not event.isAutoRepeat():self.keyPressEvent(event)
                return True
            if event.key()==Qt.Key.Key_C and event.modifiers()==Qt.KeyboardModifier.ControlModifier and (self.copy_source() is not None or self.hover_target is not None):
                event.accept()
                if event.type()==QEvent.Type.KeyPress and not event.isAutoRepeat():self.finish()
                return True
        if watched is self.canvas and event.type()==QEvent.Type.Leave:
            self.update_pointer(self.mapFromGlobal(QCursor.pos()))
        if watched is self.canvas and event.type() in [QEvent.Type.MouseMove,QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonRelease]:
            pos=event.position().toPoint()+self.canvas.pos()
            edge=self.edge_at(pos)
            if event.type()==QEvent.Type.MouseMove and not event.buttons():
                stale=self.drag_kind is not None
                self.recover_released_drag()
                self.update_pointer(pos)
                if stale:return True
            dragging=isinstance(self.drag_kind,int) and bool(event.buttons()&Qt.MouseButton.LeftButton or event.type()==QEvent.Type.MouseButtonRelease)
            if event.type()==QEvent.Type.MouseMove:
                self.canvas.setProperty('edge_hover',edge is not None or dragging)
                self.canvas.setCursor(self.edge_cursor(self.drag_kind if dragging else edge) if dragging or edge is not None else Qt.CursorShape.ArrowCursor)
                if edge is not None or dragging:self.canvas.cursor_badge.hide()
            route=dragging or (event.type()==QEvent.Type.MouseButtonPress and edge is not None and event.button()==Qt.MouseButton.LeftButton)
            if route:
                forwarded=QMouseEvent(event.type(),QPointF(pos),event.globalPosition(),event.button(),event.buttons(),event.modifiers())
                {QEvent.Type.MouseMove:self.mouseMoveEvent,QEvent.Type.MouseButtonPress:self.mousePressEvent,QEvent.Type.MouseButtonRelease:self.mouseReleaseEvent}[event.type()](forwarded)
                return True
        return super().eventFilter(watched,event)

    def mousePressEvent(self,e):
        if e.button()==Qt.MouseButton.RightButton:
            if self.rect_selected:
                self.rect_selected=None
                self.canvas.deleteLater()
                self.canvas=None
                self.border.hide()
                self.bar.hide()
                self.options.hide()
                self.start=self.end=None
                self.update()
            else:self.cancelled.emit()
            return
        if e.button()!=Qt.MouseButton.LeftButton:return
        pos=e.position().toPoint()
        self.cursor_pos=pos
        self._pressed_target=self.window_target_at(pos)
        self.manual_drag=False
        if self.rect_selected:
            edge=self.edge_at(pos)
            self.drag_kind=edge if edge is not None else ('move' if self.rect_selected.contains(pos) else 'new')
            self.drag_origin=pos
            self.drag_rect=QRect(self.rect_selected)
            if self.drag_kind=='new':
                self.border.hide()
                self.rect_selected=None
                self.canvas.deleteLater()
                self.canvas=None
                self.start=self.end=pos
                self.hover_target=self._pressed_target
            self.bar.hide()
            self.options.hide()
        else:
            self.start=self.end=pos
            self.hover_target=self._pressed_target
        self.update()

    def mouseMoveEvent(self,e):
        self.cursor_pos=e.position().toPoint()
        if self.start is None:self.update_window_preview()
        if self.rect_selected and not e.buttons():
            self.recover_released_drag()
            self.update_pointer(self.cursor_pos)
        if self.rect_selected and self.drag_kind is not None:
            delta=self.cursor_pos-self.drag_origin
            r=QRect(self.drag_rect)
            if self.drag_kind=='move':
                r.moveTopLeft(QPoint(max(0,min(self.width()-r.width(),r.x()+delta.x())),max(0,min(self.height()-r.height(),r.y()+delta.y()))))
                self.rect_selected=r
                # Reveal the frozen desktop at the new coordinates, rather than
                # carrying the old cropped pixels along with the selection.
                self.canvas.hide()
            elif isinstance(self.drag_kind,int):
                n=self.drag_kind
                if n in [0,6,7]:r.setLeft(r.left()+delta.x())
                if n in [2,3,4]:r.setRight(r.right()+delta.x())
                if n in [0,1,2]:r.setTop(r.top()+delta.y())
                if n in [4,5,6]:r.setBottom(r.bottom()+delta.y())
                self.rect_selected=r.normalized().intersected(self.rect())
                self.canvas.hide()
        elif self.start is not None and e.buttons()&Qt.MouseButton.LeftButton:
            self.end=self.cursor_pos
            if (self.end-self.start).manhattanLength()>=QApplication.startDragDistance():
                self.manual_drag=True
                self.hover_target=None
        self.update()
        if self.rect_selected is not None:
            self.border.update()
        self.position_hints()

    def mouseReleaseEvent(self,e):
        if e.button()!=Qt.MouseButton.LeftButton:return
        if self.rect_selected and self.drag_kind is not None:
            r=self.rect_selected
            previous_mode=self.mode
            if r==self.drag_rect:
                self.canvas.show()
            else:
                self.set_selection(r,keep_text=True)
                self.tool(previous_mode)
            self.drag_kind=None
            self.layout_bars()
            self.update_pointer(e.position().toPoint())
        elif self.start is not None:
            r=QRect(self.start,e.position().toPoint()).normalized().intersected(self.rect())
            target=self._pressed_target if self.window_detection and (e.position().toPoint()-self.start).manhattanLength()<QApplication.startDragDistance() else None
            self.start=self.end=None
            self._pressed_target=None
            self.manual_drag=False
            if target is not None:self.set_selection(self.target_rect(target),target)
            else:self.set_selection(r)

    def mouseDoubleClickEvent(self,e):
        if self.canvas:
            if self.mode=='选区' and e.button()==Qt.MouseButton.LeftButton:
                point=self.canvas.mapFrom(self,e.position().toPoint())
                if self.canvas.text_at(point) is not None:
                    self.drag_kind=None
                    self.canvas.show()
                    self.tool('文字')
                    self.canvas.edit_text_at(point)
                    e.accept()
                    return
            action=str(preferences().value('capture/double','复制'))
            {'复制':self.finish,'贴图':self.pin,'保存':self.save}[action]()

    def copy_source(self):
        # The selected pixels belong to the capture session, independently of
        # whichever monitor currently owns mouse/keyboard focus.
        if self.controller is not None:
            overlays=getattr(self.controller,'overlays',None)
            if isinstance(overlays,list):
                current=getattr(self.controller,'current_capture',None)
                if current in overlays and isinstance(current,Overlay) and current.canvas is not None and current.rect_selected is not None:
                    return current
                for overlay in reversed(overlays):
                    if overlay.canvas is not None and overlay.rect_selected is not None:return overlay
        return self if self.canvas is not None and self.rect_selected is not None else None

    def finish(self):
        source=self.copy_source()
        if source is None and self.hover_target is not None and self.window_detection:
            target=self.hover_target
            self.set_selection(self.target_rect(target),target)
            source=self
        if source is not None:source.selected.emit(source.canvas.pixmap())

    def clear_marks(self):
        if self.canvas:
            self.canvas.cancel_text()
            self.canvas.snapshot()
            self.canvas.text_marks.clear()
            self.canvas.number_marks.clear()
            self.canvas.selected_number=None
            self.canvas.selected_text=None
            self.canvas.text_drag=None
            self.canvas.image=self.crop(self.rect_selected).toImage()
            self.canvas.update()

    def pin(self):
        if self.canvas and self.controller:
            pix=self.canvas.pixmap()
            self.controller.clear_overlays()
            self.controller.pin(pix)

    def save(self,quick=False):
        if not self.canvas:return
        if quick:
            directory=save_directory()
            try:
                saved=save_new_png(self.canvas.pixmap(),directory)
                remember_saved_file(saved)
            except OSError as exc:
                QMessageBox.warning(self,'保存失败',str(exc))
                return
            if self.controller:self.controller.clear_overlays()
            return
        else:
            path=choose_save_path(self,'保存截图')
        if path:
            if self.canvas.pixmap().save(path,'PNG'):
                remember_saved_file(path)
                if self.controller:self.controller.clear_overlays()
            else:QMessageBox.warning(self,'保存失败','无法写入图片。')

    def ocr(self):
        if self.canvas and self.controller:
            pix=self.canvas.pixmap()
            self.controller.clear_overlays()
            d=OcrDialog(pix)
            self.controller.dialogs.append(d)
            d.show()

    def session(self,mode):
        if self.rect_selected and self.controller:
            from capture_tools import CaptureSession
            from scroll_capture import ScrollCapture
            session=(ScrollCapture(self.controller,self.screen_ref,self.rect_selected,self.frozen)
                     if mode=='scroll' else CaptureSession(self.controller,self.screen_ref,self.rect_selected,mode))
            self.controller.sessions.append(session)
            if mode=='scroll':
                # Present the replacement surface before retiring the selection.
                # Seed from the frozen selection rather than grabbing our own UI.
                session.start(initial_pixmap=self.crop(self.rect_selected),on_ready=self.controller.clear_overlays)
            else:
                self.controller.clear_overlays()
                QTimer.singleShot(200,session.start)

    def translate_popup(self):
        if self.canvas and self.controller:
            from translation_popup import TranslationPopup
            pix=self.canvas.pixmap()
            anchor=self.rect_selected.translated(self.screen_ref.geometry().topLeft())
            controller=self.controller
            controller.clear_overlays()
            popup=TranslationPopup(pix,anchor)
            controller.dialogs.append(popup)
            QTimer.singleShot(150,popup.start)

    def keyPressEvent(self,e):
        ctrl=bool(e.modifiers()&Qt.KeyboardModifier.ControlModifier)
        shift=bool(e.modifiers()&Qt.KeyboardModifier.ShiftModifier)
        key=e.key()
        if self.is_detection_toggle(e):
            if not self.detection_toggle_is_native():self.toggle_window_detection()
        elif key==Qt.Key.Key_Tab and self.rect_selected is None:
            self.detect_elements=not self.detect_elements
            self.preview_level=0
            self.update_window_preview()
            self.update()
        elif key==Qt.Key.Key_Escape:self.cancelled.emit()
        elif key in [Qt.Key.Key_Return,Qt.Key.Key_Enter] or (ctrl and key==Qt.Key.Key_C):self.finish()
        elif ctrl and key==Qt.Key.Key_T:self.pin()
        elif ctrl and key==Qt.Key.Key_S:self.save(True)
        elif shift and key==Qt.Key.Key_C:self.ocr()
        elif self.canvas:
            if key==Qt.Key.Key_Delete and self.mode=='序号':self.canvas.delete_number()
            elif key==Qt.Key.Key_L and not ctrl:self.session('scroll')
            elif key==Qt.Key.Key_G and not ctrl:self.session('video')
            elif ctrl and shift and key==Qt.Key.Key_Z:self.clear_marks()
            elif ctrl and key==Qt.Key.Key_Z:self.canvas.undo()
            elif ctrl and key==Qt.Key.Key_Y:self.canvas.redo()
            elif key in [Qt.Key.Key_Left,Qt.Key.Key_Right,Qt.Key.Key_Up,Qt.Key.Key_Down] and self.mode=='选区':
                dx={Qt.Key.Key_Left:-1,Qt.Key.Key_Right:1}.get(key,0)
                dy={Qt.Key.Key_Up:-1,Qt.Key.Key_Down:1}.get(key,0)
                r=QRect(self.rect_selected)
                if shift:r.setBottomRight(r.bottomRight()+QPoint(dx,dy))
                else:r.translate(dx,dy)
                self.set_selection(r,keep_text=True)
            else:
                mapping={'V':'选区','R':'矩形','O':'椭圆','A':'箭头','P':'画笔','H':'荧光笔','M':'马赛克','T':'文字','N':'序号'}
                if e.text().upper() in mapping:self.tool(mapping[e.text().upper()])


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.registered = []
        self.current={}
        self.startup_errors=[]
        for n,seq in keys().items():
            if seq and not self.register(n,seq):self.startup_errors.append(n)
            else:self.current[n]=seq

    @staticmethod
    def decode(seq):
        sequence=QKeySequence(seq)
        if sequence.isEmpty():return None
        if sequence.count()!=1:raise ValueError('只支持一个组合键。')
        combination=sequence[0]
        key=combination.key().value
        mods=combination.keyboardModifiers()
        modifiers=0x4000
        for qt,win in [(Qt.KeyboardModifier.ControlModifier,2),(Qt.KeyboardModifier.ShiftModifier,4),(Qt.KeyboardModifier.AltModifier,1),(Qt.KeyboardModifier.MetaModifier,8)]:
            if mods & qt:modifiers|=win
        if 0x30<=key<=0x5a:vk=key
        elif Qt.Key.Key_F1.value<=key<=Qt.Key.Key_F24.value:vk=0x70+key-Qt.Key.Key_F1.value
        else:
            vk={Qt.Key.Key_Print.value:0x2c,Qt.Key.Key_Space.value:0x20,Qt.Key.Key_Insert.value:0x2d,Qt.Key.Key_Home.value:0x24,Qt.Key.Key_End.value:0x23,Qt.Key.Key_PageUp.value:0x21,Qt.Key.Key_PageDown.value:0x22,Qt.Key.Key_QuoteLeft.value:0xc0}.get(key)
        if vk is None:raise ValueError('请使用字母、数字、F1～F24、PrintScreen 或导航键。')
        return modifiers,vk

    def register(self,n,seq):
        decoded=self.decode(seq)
        if decoded is None:return True
        if n in CAPTURE_ONLY_ACTIONS:return True
        if sys.platform!='win32' or ctypes.windll.user32.RegisterHotKey(None,n,*decoded):
            self.registered.append(n)
            return True
        return False

    def rebind(self,new):
        try:
            reserved=['Esc','Return','Enter','Tab','Ctrl+Tab','Ctrl+C','Ctrl+S','Ctrl+T','Ctrl+Z','Ctrl+Y','Ctrl+Shift+Z','Shift+C','L','G','V','R','O','A','P','H','M','T','N','Left','Right','Up','Down','Shift+Left','Shift+Right','Shift+Up','Shift+Down']
            toggle=QKeySequence(new.get(8,'')).toString(QKeySequence.SequenceFormat.PortableText)
            if toggle and toggle in {QKeySequence(value).toString(QKeySequence.SequenceFormat.PortableText) for value in reserved}:
                return False,'窗口识别快捷键与截图内置操作冲突，请使用 F8、F9 等其他按键。'
            normalized=[self.decode(v) for v in new.values() if v]
            if len(normalized)!=len(set(normalized)):return False,'存在重复快捷键，请修改后应用。'
        except ValueError as exc:return False,str(exc)
        old=dict(self.current)
        capturing=100 in self.registered or 101 in self.registered
        self.cleanup()
        self.registered=[]
        try:
            for n,seq in new.items():
                if seq and not self.register(n,seq):raise ValueError(f'快捷键 {seq} 被其他程序占用。')
        except ValueError as exc:
            self.cleanup()
            self.registered=[]
            for n,seq in old.items():
                if seq:self.register(n,seq)
            if capturing:self.start_capture_copy(old.get(8,''))
            return False,str(exc)+' 已恢复原有绑定。'
        self.current=dict(new)
        if capturing:self.start_capture_copy(new.get(8,''))
        return True,''

    def start_capture_copy(self,toggle_sequence=None):
        copied=100 in self.registered or self.register(100,'Ctrl+C')
        toggle=keys().get(8,'F8') if toggle_sequence is None else toggle_sequence
        if toggle and 101 not in self.registered:self.register(101,toggle)
        return copied

    def stop_capture_copy(self):
        for number in [100,101]:
            if number in self.registered:
                ctypes.windll.user32.UnregisterHotKey(None,number)
                self.registered.remove(number)

    def nativeEventFilter(self,event_type,message):
        if sys.platform=='win32':
            from ctypes.wintypes import MSG
            msg=MSG.from_address(int(message))
            if msg.message==0x0312:
                if msg.wParam==100:
                    QTimer.singleShot(0,self.controller.copy_capture)
                    return True,0
                if msg.wParam==101:
                    QTimer.singleShot(0,self.controller.toggle_window_detection)
                    return True,0
                fn={1:self.controller.capture,2:self.controller.clip_pin,3:self.controller.text_only,4:self.controller.restore_pin,5:self.controller.close_pins,6:self.controller.toggle_pins,7:self.controller.delayed_capture}.get(msg.wParam)
                if fn:
                    QTimer.singleShot(0,fn)
                    return True,0
        return False,0

    def cleanup(self):
        for n in self.registered:
            ctypes.windll.user32.UnregisterHotKey(None,n)
        self.registered=[]


class Home(QMainWindow):
    def __init__(self):
        super().__init__()
        self.editors,self.pins,self.dialogs,self.overlays=[],[],[],[]
        self.current_capture=None
        self.sessions=[]
        self.capture_screen_timer=QTimer(self)
        self.capture_screen_timer.setInterval(40)
        self.capture_screen_timer.timeout.connect(self.sync_capture_screen)
        self.capture_pending=False
        self.delay_countdown=CaptureCountdown(self)
        self.delay_countdown.finished.connect(self.begin_capture)
        self.delay_countdown.cancelled.connect(self.cancel_delayed_capture)
        QApplication.instance().aboutToQuit.connect(self.delay_countdown.dispose)
        self.last_pin=None
        self.settings_window=None
        self.setWindowTitle('轻截 LightSnip')
        self.setWindowIcon(icon())
        self.resize(860,620)
        home=QWidget()
        home.setObjectName('home')
        self.setCentralWidget(home)
        layout=QVBoxLayout(home)
        layout.setContentsMargins(38,32,38,28)
        brand=QHBoxLayout()
        logo=QLabel()
        logo.setPixmap(icon().pixmap(64,64))
        brand.addWidget(logo)
        heading=QLabel('轻截  LightSnip')
        heading.setObjectName('title')
        brand.addWidget(heading)
        brand.addStretch()
        layout.addLayout(brand)
        subtitle=QLabel('轻轻一截，即刻读懂。')
        subtitle.setObjectName('muted')
        layout.addWidget(subtitle)
        layout.addSpacing(24)
        b=QPushButton('＋  开始截图                 Ctrl + Shift + 1')
        b.setObjectName('primary')
        b.setMinimumHeight(68)
        b.clicked.connect(self.capture)
        layout.addWidget(b)
        grid=QGridLayout()
        for i,(label,fn) in enumerate([('打开图片',self.open_image),('剪贴板贴图  Ctrl+Shift+2',self.clip_pin),('文字翻译  Ctrl+Shift+3',self.text_only),('延时截图',self.delayed_capture)]):
            btn=QPushButton(label)
            btn.setMinimumHeight(56)
            btn.clicked.connect(fn)
            grid.addWidget(btn,i//2,i%2)
        layout.addLayout(grid)
        layout.addSpacing(20)
        layout.addWidget(QLabel('截图 · 箭头与标注 · 马赛克 · 置顶贴图 · 本地 OCR · 免费联网翻译'))
        note=QLabel('无账号系统，无 API 密钥。\n翻译使用 MyMemory 匿名服务，免费额度 5,000 字符/天；点击翻译才联网。')
        note.setObjectName('muted')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.hotkeys=Hotkeys(self)
        QApplication.instance().installNativeEventFilter(self.hotkeys)
        missing=set([1,2,3])-set(self.hotkeys.registered)
        self.statusBar().showMessage('部分快捷键被占用，请使用窗口或托盘按钮。' if missing else '全局快捷键已就绪')
        self.tray=QSystemTrayIcon(icon(),self)
        self.rebuild_tray()
        self.tray.setToolTip('轻截 LightSnip')
        self.tray.activated.connect(lambda reason: self.capture() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()
        QApplication.instance().aboutToQuit.connect(self.hotkeys.cleanup)

    def rebuild_tray(self):
        from settings_ui import ACTION_NAMES
        menu=QMenu()
        funcs={1:self.capture,2:self.clip_pin,3:self.text_only,4:self.restore_pin,5:self.close_pins,6:self.toggle_pins,7:self.delayed_capture,8:self.toggle_window_detection}
        for n,name in ACTION_NAMES.items():
            sequence=keys()[n]
            menu.addAction(name+('    '+sequence if sequence else ''),funcs[n])
        menu.addSeparator()
        menu.addAction('打开图片',self.open_image)
        menu.addAction('配置',self.show_settings)
        menu.addSeparator()
        menu.addAction('退出',QApplication.instance().quit)
        self.tray_menu=menu
        self.tray.setContextMenu(menu)

    def show_settings(self):
        if self.delay_countdown.running:self.delay_countdown.cancel()
        if self.settings_window is None:self.settings_window=SettingsWindow(self)
        self.settings_window.showNormal()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def restore_pin(self):
        if self.last_pin is not None:self.pin(self.last_pin)

    def close_pins(self):
        for pin in self.pins:
            if not pin.closed_by_user:pin.close()

    def toggle_pins(self):
        active=[pin for pin in self.pins if not pin.closed_by_user]
        visible=any(pin.isVisible() for pin in active)
        for pin in active:pin.setVisible(not visible)

    def delayed_capture(self):
        if self.delay_countdown.running:
            self.delay_countdown.cancel()
            return
        if self.capture_pending or self.overlays:return
        self.capture_pending=True
        self.was_visible=False
        if self.settings_window:self.settings_window.hide()
        self.hide()
        delay=preferences().value('capture/delay',3,type=int)
        screen=QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        self.delay_countdown.start(delay,screen,keys().get(7,''))

    def cancel_delayed_capture(self):
        self.capture_pending=False

    def capture(self):
        if self.overlays or self.capture_pending:
            return
        self.capture_pending=True
        self.was_visible=self.isVisible()
        self.hide()
        if self.settings_window:self.settings_window.hide()
        QTimer.singleShot(220,self.begin_capture)

    def begin_capture(self):
        self.capture_pending=False
        # Freeze every display before showing any overlay. Selection is per-display.
        screens=[(s,s.grabWindow(0)) for s in QApplication.screens()]
        window_catalog=snapshot_windows([screen for screen,_ in screens])
        self.region_scanner=RegionScanner(window_catalog,self)
        for screen,frozen in screens:
            overlay=Overlay(screen,frozen,self,window_catalog)
            overlay.selected.connect(self.captured)
            overlay.cancelled.connect(self.cancel_capture)
            self.overlays.append(overlay)
        self.hotkeys.start_capture_copy()
        for overlay in self.overlays:
            overlay.show()
        self.sync_capture_screen()
        self.capture_screen_timer.start()

    def sync_capture_screen(self,cursor_pos=None):
        pos=QCursor.pos() if cursor_pos is None else cursor_pos
        editing=any(item.canvas is not None and item.canvas.text_editor is not None for item in self.overlays)
        for overlay in self.overlays:
            active=overlay.geometry().contains(pos)
            was_active=overlay.active_screen
            overlay.set_capture_active(active,pos)
            # An inline editor owns its focus until the user commits or cancels it.
            if active and not editing and (not was_active or not overlay.isActiveWindow()) and QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None:
                overlay.activateWindow()

    def clear_overlays(self):
        scanner=getattr(self,'region_scanner',None)
        if scanner is not None:
            scanner.stop()
            self.region_scanner=None
        hotkeys=getattr(self,'hotkeys',None)
        if hotkeys is not None:hotkeys.stop_capture_copy()
        self.capture_screen_timer.stop()
        self.current_capture=None
        for o in self.overlays:
            o.close()
            o.deleteLater()
        self.overlays=[]

    def copy_capture(self):
        # Windows delivers the capture-only Ctrl+C even during native focus
        # transitions, before a screenshot QWidget has received keyboard focus.
        for overlay in self.overlays:
            source=overlay.copy_source()
            if source is not None:
                source.finish()
                return
        for overlay in self.overlays:
            if overlay.active_screen and overlay.hover_target is not None:
                overlay.finish()
                return

    def set_window_detection(self,enabled):
        cfg=preferences()
        cfg.setValue('capture/window_detection',bool(enabled))
        cfg.sync()
        for overlay in self.overlays:overlay.set_window_detection(enabled)
        settings=getattr(self,'settings_window',None)
        if settings is not None:
            control=settings.bindings.get('capture/window_detection')
            if control:control[0].setChecked(enabled)

    def toggle_window_detection(self):
        self.set_window_detection(not flag('capture/window_detection',True))

    def cancel_capture(self):
        self.clear_overlays()
        if self.was_visible:
            self.show()

    def captured(self,pix):
        QApplication.clipboard().setPixmap(pix)
        self.clear_overlays()

    def edit(self,pix):
        if pix.isNull():
            QMessageBox.warning(self,'读取失败','无法读取图片。')
            return
        editor=Editor(pix,self)
        self.editors.append(editor)
        editor.show()

    def pin(self,pix):
        pin=Pin(pix,self)
        self.pins.append(pin)
        if flag('pin/copy',False):QApplication.clipboard().setPixmap(pix)

    def clip_pin(self):
        pix=QApplication.clipboard().pixmap()
        if pix.isNull():
            QMessageBox.information(self,'剪贴板贴图','请先复制一张图片。')
        else:
            self.pin(pix)

    def text_only(self):
        d=TextDialog(parent=self)
        self.dialogs.append(d)
        d.show()

    def open_image(self):
        path,_=QFileDialog.getOpenFileName(self,'打开图片','','图片 (*.png *.jpg *.jpeg *.bmp *.webp)')
        if path:
            self.edit(QPixmap(path))

    def closeEvent(self,event):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            event.ignore()
        else:
            QApplication.instance().quit()


def main():
    if '--self-test-elements' in sys.argv:
        output=Path(sys.argv[sys.argv.index('--self-test-elements')+1])
        output.mkdir(parents=True,exist_ok=True)
        try:
            from verify_element_detection_ui import main as verify_elements
            return verify_elements(output,Overlay)
        except Exception:
            import traceback
            (output/'element-test-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
            return
    app=QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('LightSnip')
    app.setOrganizationName('LightSnip')
    app.setStyleSheet(LIGHT_STYLE)
    app.setWindowIcon(icon())
    app.setQuitOnLastWindowClosed(False)
    if '--self-test' in sys.argv:
        import json
        from verify_text_ui import verify_text_workflow,verify_number_workflow
        result={}
        try:
            pix=QPixmap(650,140)
            pix.fill(QColor('white'))
            p=QPainter(pix)
            p.setPen(QColor('black'))
            p.setFont(QFont('Arial',32))
            p.drawText(20,85,'Hello LightSnip 2026')
            p.end()
            result['ocr']=recognize(png_bytes(pix))
            assert '2026' in result['ocr']
            editor=Editor(pix,None)
            result['editor']=not editor.canvas.pixmap().isNull()
            result['screen_capture']=not app.primaryScreen().grabWindow(0).isNull()
            assert result['editor'] and result['screen_capture']
            result['text_workflow_cycles']=verify_text_workflow(Overlay,100 if '--stress-text' in sys.argv else 20)
            verify_number_workflow(Overlay)
            result['number_delete_and_reuse']=True
            if '--native-text-list' in sys.argv:
                from verify_text_ui import verify_native_text_list
                result['native_text_list_screens']=verify_native_text_list(Overlay)
            result['ok']=True
        except Exception as exc:
            result['ok']=False
            result['error']=str(exc)
        output=Path(sys.argv[sys.argv.index('--self-test')+1])
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    socket=QLocalSocket()
    socket.connectToServer('LightSnip.Local.SingleInstance.v27')
    if socket.waitForConnected(300):
        socket.write(b'background' if '--autostart' in sys.argv else b'show')
        socket.waitForBytesWritten(300)
        return
    server=QLocalServer()
    QLocalServer.removeServer('LightSnip.Local.SingleInstance.v27')
    server.listen('LightSnip.Local.SingleInstance.v27')
    home=Home()
    def show_existing():
        client=server.nextPendingConnection()
        if client:
            client.waitForReadyRead(300)
            command=bytes(client.readAll())
            client.disconnectFromServer()
            client.deleteLater()
            if command!=b'background':home.show_settings()
    server.newConnection.connect(show_existing)
    app.setStyleSheet(LIGHT_STYLE)
    if '--autostart' not in sys.argv and flag('system/show_settings',True):home.show_settings()
    sys.exit(app.exec())


if __name__=='__main__':
    main()
