from PySide6.QtCore import Qt,QPoint,QRect,QTimer,QThreadPool
from PySide6.QtGui import QColor,QGuiApplication,QPainter
from PySide6.QtWidgets import (QWidget,QFrame,QVBoxLayout,QHBoxLayout,QLabel,
    QToolButton,QGraphicsDropShadowEffect,QApplication,QScrollArea)
from ui_icons import lucide


class TranslationPopup(QWidget):
    def __init__(self,pix,anchor):
        super().__init__(None,Qt.WindowType.Popup|Qt.WindowType.FramelessWindowHint|Qt.WindowType.NoDropShadowWindowHint)
        self.setWindowTitle('轻截 · 翻译')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.anchor=QRect(anchor)
        self.translation=''
        self.jobs=[]
        self.payload=None
        from app import png_bytes
        self.payload=png_bytes(pix)
        root=QVBoxLayout(self)
        root.setContentsMargins(16,14,16,18)
        card=QFrame()
        card.setObjectName('translationCard')
        card.setStyleSheet('QFrame#translationCard {background:white;border:1px solid #dedfe3;border-radius:5px;} QLabel {background:transparent;color:#272b30;border:0;font-size:14px;} QToolButton {background:transparent;border:0;padding:3px;border-radius:3px;} QToolButton:hover {background:#edf1f5;}')
        self.card=card
        root.addWidget(card)
        content=QVBoxLayout(card)
        content.setContentsMargins(16,7,10,14)
        content.setSpacing(4)
        buttons=QHBoxLayout()
        buttons.addStretch()
        self.copy=QToolButton()
        self.copy.setIcon(lucide('copy','#858b92',14))
        self.copy.setToolTip('复制译文')
        self.copy.setEnabled(False)
        self.copy.clicked.connect(lambda:QApplication.clipboard().setText(self.translation))
        buttons.addWidget(self.copy)
        close=QToolButton()
        close.setIcon(lucide('x','#858b92',14))
        close.setToolTip('关闭')
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        content.addLayout(buttons)
        self.text=QLabel('正在识别并翻译…')
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.scroll=QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet('QScrollArea,QScrollArea>QWidget>QWidget {background:transparent;border:0;}')
        self.scroll.setWidget(self.text)
        content.addWidget(self.scroll)
        screen=QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        self.available=screen.availableGeometry()
        self.setFixedWidth(min(max(300,min(anchor.width(),500)),self.available.width()-24))
        self.place()

    def place(self):
        available=self.available.adjusted(8,8,-8,-8)
        self.setFixedWidth(min(max(300,min(self.anchor.width(),500)),available.width()))
        self.ensurePolished()
        # Reserve room for the card margins, action buttons and shadow; long
        # translations scroll inside the card instead of extending off-screen.
        overhead=14+18+7+14+4+max(24,self.copy.sizeHint().height())
        text_width=max(1,self.width()-32-26-18)
        text_height=max(self.text.fontMetrics().lineSpacing(),self.text.heightForWidth(text_width))+8
        height=min(available.height(),max(100,text_height+overhead))
        self.setFixedHeight(height)
        self.scroll.setMinimumHeight(0)
        x=max(available.left(),min(self.anchor.left()-16,available.right()-self.width()+1))
        below=self.anchor.bottom()+5
        above=self.anchor.top()-height-4
        y=below if below+height-1<=available.bottom() else above
        y=max(available.top(),min(y,available.bottom()-height+1))
        self.move(x,y)
        self.layout().activate()

    def paintEvent(self,event):
        p=QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(),Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        base=self.card.geometry().translated(0,3)
        for spread in range(12,0,-1):
            p.setBrush(QColor(0,0,0,2 if spread>6 else 4))
            p.drawRoundedRect(base.adjusted(-spread,-spread,spread,spread),5+spread,5+spread)
        p.end()

    def start(self):
        self.show()
        self.place()
        from services import recognize
        self.work(lambda:recognize(self.payload),self.recognized)

    def work(self,fn,done):
        from app import Job
        job=Job(fn)
        self.jobs.append(job)
        job.signals.result.connect(done)
        job.signals.error.connect(self.failed)
        QThreadPool.globalInstance().start(job)

    def recognized(self,text):
        if not self.isVisible():return
        if not text.strip():
            self.failed('未识别到文字')
            return
        from services import translate,source_language
        # Chinese text translates into English; other supported languages into Chinese.
        target='en' if source_language(text)=='zh-CN' else 'zh-CN'
        self.work(lambda:translate(text,'auto',target),self.translated)

    def translated(self,text):
        if not self.isVisible():return
        self.translation=text
        self.text.setText(text)
        self.copy.setEnabled(True)
        self.place()

    def failed(self,message):
        if not self.isVisible():return
        self.text.setText('翻译失败：'+message[:200])
        self.place()

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.close()
        else:super().keyPressEvent(event)

    def mousePressEvent(self,event):
        if self.childAt(event.position().toPoint()) is None:self.close()
        else:super().mousePressEvent(event)
