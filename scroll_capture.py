"""Region-only live scrolling capture with a pass-through selection hole."""
import ctypes
import threading
import time
from ctypes import wintypes
from PySide6.QtCore import Qt,QRect,QPoint,QSize,QTimer,QObject,Signal
from PySide6.QtGui import QPainter,QColor,QPen,QRegion,QPixmap,QImage,QCursor
from PySide6.QtWidgets import QWidget,QToolBar,QLabel,QComboBox,QFileDialog,QToolButton
from ui_icons import lucide,TOOLBAR_STYLE
from scroll_stitcher import ContentStitcher
from annotation_tools import BORDER_WIDTH
from file_names import choose_save_path,remember_saved_file
from theme import ThemedComboBox


class WheelMonitor(QObject):
    wheel=Signal()
    failed=Signal()

    def __init__(self):
        super().__init__()
        self.thread_id=None
        self.worker_thread=None
        self.stopping=False

    def start(self):
        self.worker_thread=threading.Thread(target=self.run,daemon=True)
        self.worker_thread.start()

    def run(self):
        user=ctypes.WinDLL('user32',use_last_error=True)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        callback_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,ctypes.c_int,ctypes.c_size_t,ctypes.c_ssize_t)
        user.SetWindowsHookExW.argtypes=[ctypes.c_int,callback_type,wintypes.HINSTANCE,wintypes.DWORD]
        user.SetWindowsHookExW.restype=wintypes.HANDLE
        user.CallNextHookEx.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_size_t,ctypes.c_ssize_t]
        user.CallNextHookEx.restype=ctypes.c_ssize_t
        user.UnhookWindowsHookEx.argtypes=[wintypes.HANDLE]
        kernel.GetModuleHandleW.argtypes=[wintypes.LPCWSTR]
        kernel.GetModuleHandleW.restype=wintypes.HMODULE
        @callback_type
        def callback(code,message,data):
            if code>=0 and message in (0x020A,0x020E):self.wheel.emit()
            return user.CallNextHookEx(None,code,message,data)
        self.callback=callback
        msg=wintypes.MSG()
        user.PeekMessageW(ctypes.byref(msg),None,0,0,0)
        self.thread_id=kernel.GetCurrentThreadId()
        hook=user.SetWindowsHookExW(14,callback,kernel.GetModuleHandleW(None),0)
        if not hook:
            self.failed.emit()
            return
        try:
            while not self.stopping:
                value=user.GetMessageW(ctypes.byref(msg),None,0,0)
                if value<=0:break
                user.TranslateMessage(ctypes.byref(msg))
                user.DispatchMessageW(ctypes.byref(msg))
        finally:user.UnhookWindowsHookEx(hook)

    def stop(self):
        self.stopping=True
        if self.thread_id:ctypes.windll.user32.PostThreadMessageW(self.thread_id,0x0012,0,0)
        if self.worker_thread is not None and self.worker_thread.is_alive() and threading.current_thread()!=self.worker_thread:
            self.worker_thread.join(timeout=0.5)


def image_array(pix):
    import numpy as np
    import cv2
    img=pix.toImage().convertToFormat(QImage.Format.Format_RGB888)
    pixels=np.frombuffer(img.constBits(),np.uint8).reshape(img.height(),img.bytesPerLine())
    rgb=pixels[:,:img.width()*3].reshape(img.height(),img.width(),3)
    return cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)


def array_pixmap(frame):
    import cv2
    rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
    return QPixmap.fromImage(QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format.Format_RGB888).copy())


class ScrollCapture(QWidget):
    def __init__(self,controller,screen,region,frozen):
        super().__init__(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.controller,self.screen,self.region,self.frozen=controller,screen,QRect(region),frozen
        self.setWindowTitle('轻截 · 滚动长截图')
        self.setGeometry(screen.geometry())
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.parts=[]
        self.previous=None
        self.stitcher=None
        self.finished=False
        self.paused=False
        self.last_wheel=0
        self.started=False
        self.vertical=True
        self.total=0
        self.transition_cover=False
        self.transition_callback=None
        self.transition_scheduled=False
        self.bar=QToolBar(self)
        self.bar.setMovable(False)
        self.bar.setStyleSheet(TOOLBAR_STYLE)
        self.bar.setIconSize(QSize(20,20))
        self.bar.addAction(lucide('grip-vertical','#000000',14),'长截图选区')
        self.dimensions=QLabel()
        self.dimensions.setContentsMargins(4,0,6,0)
        self.bar.addWidget(self.dimensions)
        self.bar.addAction(lucide('arrow-down-up'),'滚动方向')
        self.direction=ThemedComboBox()
        self.direction.addItems(['纵向','横向'])
        self.direction.currentIndexChanged.connect(self.change_direction)
        self.bar.addWidget(self.direction)
        self.bar.addSeparator()
        self.pause_action=self.bar.addAction(lucide('pause'),'暂停/继续',self.pause)
        self.bar.addAction(lucide('scissors'),'完成并编辑',lambda:self.complete('edit'))
        self.bar.addAction(lucide('scan-letter-a'),'识别长图文字',lambda:self.complete('ocr'))
        self.bar.addAction(lucide('pin'),'贴图',lambda:self.complete('pin'))
        self.bar.addAction(lucide('download'),'保存长图',lambda:self.complete('save'))
        self.bar.addAction(lucide('x'),'取消',self.cancel)
        self.bar.addAction(lucide('copy'),'复制长图',lambda:self.complete('copy'))
        self.preview=QLabel(self)
        self.preview.setStyleSheet('background:white;border:2px solid #3286ff;')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignHCenter)
        self.tip=QLabel('在蓝框内滚动鼠标，即开始长截图',self)
        self.tip.setStyleSheet('background:#25272a;color:white;padding:5px 9px;border-radius:5px;font-size:12px;')
        self.monitor=WheelMonitor()
        self.monitor.wheel.connect(self.on_wheel)
        self.monitor.failed.connect(lambda:self.tip.setText('无法监听滚轮，请取消后重新开启长截图'))
        self.timer=QTimer(self)
        self.timer.setInterval(110)
        self.timer.timeout.connect(self.tick)
        self.refresh_preview()

    def start(self,initial_pixmap=None,on_ready=None):
        self.transition_cover=initial_pixmap is not None
        self.transition_callback=on_ready
        self.previous=image_array(initial_pixmap) if initial_pixmap is not None else self.grab()
        self.parts=[self.previous]
        self.total=self.previous.shape[0]
        self.refresh_preview()
        self.show()
        if not self.transition_cover:self.begin_monitoring()

    def begin_monitoring(self):
        self.monitor.start()
        self.timer.start()

    def finish_transition(self):
        if self.finished:return
        if self.transition_callback:
            callback=self.transition_callback
            self.transition_callback=None
            callback()
        # Keep the newly painted frozen surface over the old window's teardown.
        QTimer.singleShot(0,self.reveal_live_region)

    def reveal_live_region(self):
        if self.finished:return
        self.transition_cover=False
        self.apply_mask()
        self.update()
        self.begin_monitoring()

    def grab(self):
        full=self.screen.grabWindow(0)
        sx,sy=full.width()/self.screen.geometry().width(),full.height()/self.screen.geometry().height()
        r=self.region
        # Capture only the chosen region; the blue frame is painted outside it.
        return image_array(full.copy(QRect(round(r.x()*sx),round(r.y()*sy),round(r.width()*sx),round(r.height()*sy))))

    def cursor_inside(self):
        return self.region.translated(self.screen.geometry().topLeft()).contains(QCursor.pos())

    def on_wheel(self):
        if self.finished or self.paused or not self.cursor_inside():return
        self.last_wheel=time.monotonic()
        self.started=True
        self.tip.setText('正在拼接 · 缓慢向下滚动，点击工具栏完成')

    def tick(self):
        if self.finished or self.paused or not self.started:return
        # Continue briefly after wheel events to allow smooth scrolling to settle.
        if time.monotonic()-self.last_wheel>1.2:return
        frame=self.grab()
        before=self.previous if self.vertical else self.previous.transpose(1,0,2)
        after=frame if self.vertical else frame.transpose(1,0,2)
        if self.stitcher is None:self.stitcher=ContentStitcher(before)
        try:shift=self.stitcher.append(after)
        except OverflowError:
            self.paused=True
            self.tip.setText('已达长度上限，请复制或保存')
            return
        if shift is None:
            self.tip.setText('重叠区域不足，请回滚少许后缓慢向下滚动')
            return
        if not shift:return
        full=self.stitcher.image()
        self.parts=[full if self.vertical else full.transpose(1,0,2)]
        self.total=full.shape[0]
        self.previous=frame
        self.tip.setText('正在拼接 · 点击工具栏复制或保存')
        self.refresh_preview()

    def full_frame(self):
        import numpy as np
        return np.concatenate(self.parts,axis=0 if self.vertical else 1)

    def refresh_preview(self):
        r=self.region
        if self.parts:
            full=self.full_frame()
            self.dimensions.setText(f'{full.shape[1]} × {full.shape[0]}')
        self.bar.adjustSize()
        bw,bh=self.bar.sizeHint().width(),self.bar.sizeHint().height()
        x=max(4,min(r.right()-bw,self.width()-bw-4))
        y=r.bottom()+8
        if y+bh>self.height():y=max(0,r.top()-bh-8)
        # If no outside toolbar space exists, move it onto another monitor.
        self.bar.move(x,y)
        self.bar.setFixedSize(bw,bh)
        preview_w=min(190,max(80,r.width()//4))
        px=r.right()+12
        if px+preview_w>self.width():px=r.left()-preview_w-12
        preview_h=min(r.height(),max(100,self.height()-70))
        self.preview.setVisible(px>=0 and px+preview_w<=self.width())
        self.preview.setGeometry(max(0,px),r.bottom()-preview_h+1,preview_w,preview_h)
        if self.parts:
            full=self.full_frame()
            pix=array_pixmap(full)
            self.preview.setPixmap(pix.scaled(QSize(preview_w-4,preview_h-4),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        self.tip.adjustSize()
        self.tip.move(max(0,min(r.left(),self.width()-self.tip.width())),max(0,r.top()-self.tip.height()-8))
        self.apply_mask()
        self.update()

    def apply_mask(self):
        if self.transition_cover:
            self.setMask(QRegion(self.rect()))
            return
        # Native window hole: wheel and clicks reach the underlying app directly.
        mask=QRegion(self.rect()).subtracted(QRegion(self.region))
        for widget in [self.bar,self.preview,self.tip]:
            if not widget.isHidden():mask=mask.united(QRegion(widget.geometry()))
        self.setMask(mask)

    def paintEvent(self,event):
        with QPainter(self) as p:
            p.drawPixmap(self.rect(),self.frozen)
            p.fillRect(self.rect(),QColor(0,0,0,105))
            if self.transition_cover:
                p.save()
                try:
                    p.setClipRect(self.region)
                    p.drawPixmap(self.rect(),self.frozen)
                finally:
                    p.restore()
            p.setPen(QPen(QColor('#3286ff'),BORDER_WIDTH))
            p.drawRect(self.region)
        if self.transition_cover and not self.transition_scheduled:
            self.transition_scheduled=True
            QTimer.singleShot(0,self.finish_transition)

    def pause(self):
        self.paused=not self.paused
        self.pause_action.setIcon(lucide('play' if self.paused else 'pause'))
        self.tip.setText('已暂停，点击继续后在框内滚动' if self.paused else '在蓝框内滚动鼠标继续拼接')
        self.last_wheel=0
        self.refresh_preview()

    def change_direction(self,index):
        self.stitcher=None
        if self.parts:
            self.previous=self.grab()
            self.parts=[self.previous]
        self.vertical=index==0
        self.total=self.previous.shape[0 if self.vertical else 1] if self.previous is not None else 0
        self.last_wheel=0
        self.started=False
        self.refresh_preview()

    def complete(self,action):
        if not self.parts:return
        self.paused=True
        pix=array_pixmap(self.full_frame())
        if action=='save':
            path=choose_save_path(self,'保存长截图','轻截长截图')
            if not path:return
            if not pix.save(path,'PNG'):
                self.tip.setText('保存失败，请选择其他目录')
                return
            remember_saved_file(path)
        self.cancel()
        if action=='copy':self.controller.captured(pix)
        elif action=='edit':self.controller.edit(pix)
        elif action=='pin':self.controller.pin(pix)
        elif action=='ocr':
            from app import OcrDialog
            dialog=OcrDialog(pix)
            self.controller.dialogs.append(dialog)
            dialog.show()

    def cancel(self):
        if self.transition_callback:
            callback=self.transition_callback
            self.transition_callback=None
            callback()
        self.finished=True
        self.timer.stop()
        self.monitor.stop()
        self.close()

    def closeEvent(self,event):
        self.finished=True
        self.timer.stop()
        self.monitor.stop()
        event.accept()
