"""Live desktop dimming with a region-only scrolling capture hole."""
import ctypes
import threading
import time
from ctypes import wintypes
from PySide6.QtCore import Qt,QRect,QPoint,QSize,QTimer,QObject,Signal
from PySide6.QtGui import QPainter,QColor,QPen,QRegion,QPixmap,QImage,QCursor
from PySide6.QtWidgets import QWidget,QToolBar,QLabel,QComboBox,QFileDialog,QToolButton
from ui_icons import lucide,TOOLBAR_STYLE,IconToolBar as QToolBar
from scroll_stitcher import ContentStitcher
from annotation_tools import BORDER_WIDTH
from file_names import choose_save_path,remember_saved_file
from theme import ThemedComboBox


def send_region_wheel(point,delta,horizontal=False,expected_root=None):
    """Send one bounded wheel message to the app under the selection, not the cursor.

    Recheck the target each time so switching/closing a window cannot scroll a
    different application. SendMessageTimeout also bounds unresponsive targets.
    """
    import os
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.WindowFromPoint.argtypes=[wintypes.POINT]
    user.WindowFromPoint.restype=wintypes.HWND
    user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT]
    user.GetAncestor.restype=wintypes.HWND
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.SendMessageTimeoutW.argtypes=[wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t,wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
    user.SendMessageTimeoutW.restype=ctypes.c_ssize_t
    target=user.WindowFromPoint(wintypes.POINT(point.x(),point.y()))
    if not target:return None
    root=user.GetAncestor(target,2)
    pid=wintypes.DWORD()
    user.GetWindowThreadProcessId(target,ctypes.byref(pid))
    if pid.value==os.getpid() or (expected_root is not None and root!=expected_root):return None
    coordinates=(point.x()&0xffff)|((point.y()&0xffff)<<16)
    result=ctypes.c_size_t()
    ok=user.SendMessageTimeoutW(target,0x020E if horizontal else 0x020A,(delta&0xffff)<<16,coordinates,0x0002,80,ctypes.byref(result))
    return root if ok else None


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


class AutoWheelPump(QObject):
    """Keep small wheel pulses flowing while the GUI thread stitches frames."""
    failed=Signal(object)

    def __init__(self,point,sign,horizontal,target,rate):
        super().__init__()
        self.point,self.sign,self.horizontal,self.target=QPoint(point),sign,horizontal,target
        self.rate=rate
        self.total_sent=0
        self.lock=threading.Lock()
        self.stopping=threading.Event()
        self.thread=None

    def set_rate(self,rate):
        with self.lock:self.rate=rate

    def stats(self):
        with self.lock:return self.total_sent,self.rate

    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def run(self):
        previous=time.monotonic()
        remainder=0.0
        while not self.stopping.wait(.008):
            now=time.monotonic()
            # Do not issue a catch-up jump after a scheduler/target stall.
            elapsed=min(.032,max(0,now-previous))
            previous=now
            with self.lock:rate=self.rate
            if not rate:
                remainder=0
                continue
            remainder+=elapsed*rate
            delta=int(remainder)
            if delta<1:continue
            remainder-=delta
            root=send_region_wheel(self.point,self.sign*delta,self.horizontal,self.target)
            if root is None:
                self.stopping.set()
                self.failed.emit(self)
                return
            with self.lock:self.total_sent+=delta

    def stop(self):
        self.stopping.set()
        if self.thread is not None and self.thread.is_alive() and threading.current_thread()!=self.thread:
            self.thread.join(timeout=.2)


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
        # A native translucent surface lets the compositor dim the live
        # desktop outside the crop, without taking repeated desktop snapshots.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
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
        self.reverse=False
        self.automatic=False
        self.auto_target=None
        self.auto_point=None
        self.auto_pump=None
        self.auto_rate=120.0
        self.auto_progress_units=0
        self.auto_progress_time=0
        self.auto_failed_time=None
        self.auto_last_units=0
        self.auto_settling=False
        self.settle_frame=None
        self.settle_action=None
        self.settle_message=None
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
        self.direction.addItems(['纵向 · 向下','横向 · 向右','纵向 · 向上','横向 · 向左'])
        self.direction.setToolTip('选择长截图的滚动方向')
        self.direction.currentIndexChanged.connect(self.change_direction)
        self.bar.addWidget(self.direction)
        self.bar.addSeparator()
        self.auto_action=self.bar.addAction(lucide('play'),'自动滚动截图',self.toggle_auto)
        self.auto_action.setCheckable(True)
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
        self.settle_timer=QTimer(self)
        self.settle_timer.setSingleShot(True)
        self.settle_timer.setInterval(180)
        self.settle_timer.timeout.connect(self.finish_auto_stop)
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
        if self.finished or self.paused or self.automatic or self.auto_settling or not self.cursor_inside():return
        self.last_wheel=time.monotonic()
        self.started=True
        self.tip.setText('正在拼接 · 沿所选方向缓慢滚动，点击工具栏完成')

    def toggle_auto(self):
        if self.automatic:
            self.begin_auto_stop('已停止自动滚动，可继续手动滚动或复制保存')
            return
        if self.finished or self.transition_cover or self.auto_settling:return
        self.paused=False
        self.pause_action.setIcon(lucide('pause'))
        self.automatic=True
        self.auto_action.setChecked(True)
        self.auto_action.setIcon(lucide('square'))
        self.auto_action.setToolTip('停止自动滚动截图')
        self.auto_target=None
        from window_detection import snapshot_windows
        catalog=snapshot_windows([self.screen])
        point=self.region.center()+self.screen.geometry().topLeft()
        mapping=next((m for m in catalog.mappings if m.logical.contains(point)),None)
        self.auto_point=mapping.native_point(point) if mapping else point
        self.auto_rate=120.0
        self.auto_progress_time=time.monotonic()
        self.auto_progress_units=0
        self.auto_last_units=0
        self.auto_failed_time=None
        self.started=True
        sign=(1 if self.reverse else -1) if self.vertical else (-1 if self.reverse else 1)
        # Resolve and validate the target before starting the continuous pump.
        root=send_region_wheel(self.auto_point,sign,not self.vertical,None)
        if root is None:
            self.stop_auto('自动滚动已停止：目标窗口变化或不响应，可在选区内手动滚动')
            return
        self.auto_target=root
        self.auto_pump=AutoWheelPump(self.auto_point,sign,not self.vertical,root,self.auto_rate)
        self.auto_pump.failed.connect(self.auto_target_failed)
        self.auto_pump.start()
        self.tip.setText('自动滚动中 · 再次点击自动滚动按钮可停止')
        self.refresh_preview()

    def stop_auto(self,message=None):
        self.automatic=False
        if self.auto_pump is not None:
            self.auto_pump.stop()
            self.auto_pump=None
        self.settle_timer.stop()
        self.auto_settling=False
        self.settle_frame=None
        self.settle_action=None
        self.auto_action.setEnabled(True)
        self.auto_action.setChecked(False)
        self.auto_action.setIcon(lucide('play'))
        self.auto_action.setToolTip('自动滚动截图')
        self.last_wheel=0
        if message:
            self.tip.setText(message)
            self.refresh_preview()

    def auto_target_failed(self,pump):
        if self.automatic and self.auto_pump is pump:
            self.stop_auto('自动滚动已停止：目标窗口变化或不响应，可在选区内手动滚动')

    def begin_auto_stop(self,message=None,action=None):
        self.stop_auto()
        self.auto_settling=True
        self.settle_message=message
        self.settle_action=action
        self.settle_frame=None
        self.settle_stable=0
        self.settle_deadline=time.monotonic()+.9
        self.auto_action.setEnabled(False)
        self.settle_timer.start()

    def finish_auto_stop(self):
        if self.finished or not self.auto_settling:return
        action,message=self.settle_action,self.settle_message
        # Include the final small scroll and the target application's animation
        # tail before allowing copy/save. Normal scrolling never waits here.
        import numpy as np
        frame=self.grab()
        self.append_frame(frame)
        if self.auto_settling:
            stable=self.settle_frame is not None and np.array_equal(frame,self.settle_frame)
            self.settle_stable=self.settle_stable+1 if stable else 0
            self.settle_frame=frame
            if self.settle_stable<2 and time.monotonic()<self.settle_deadline:
                self.settle_timer.start(80)
                return
        self.auto_settling=False
        self.settle_frame=None
        self.settle_action=None
        self.auto_action.setEnabled(True)
        if message:self.tip.setText(message)
        self.refresh_preview()
        if action:self.complete(action)

    def auto_tick(self):
        pump=self.auto_pump
        if pump is None:return
        now=time.monotonic()
        frame=self.grab()
        units,_=pump.stats()
        shift=self.append_frame(frame)
        if not self.automatic:return
        if shift is None:
            # Only a failed match pauses wheel input to let an animation settle.
            # Keep the last good frame, and never append an unreliable strip.
            pump.set_rate(0)
            if self.auto_failed_time is None:self.auto_failed_time=now
            elif now-self.auto_failed_time>1.2:
                self.stop_auto('无法可靠拼接，已停止自动滚动，请回滚少许后继续')
            return
        if shift==0:
            if self.auto_failed_time is not None:
                self.auto_failed_time=None
                pump.set_rate(self.auto_rate)
            if units-self.auto_progress_units>=240 and now-self.auto_progress_time>=1.5:
                self.begin_auto_stop('画面已不再滚动，自动截图已停止 · 可复制或保存')
                return
        else:
            sent=max(1,units-self.auto_last_units)
            length=frame.shape[0 if self.vertical else 1]
            # Target about 45% of a viewport per second; infer each app's
            # actual wheel scale and leave enough overlap even on slow PCs.
            target=max(20,min(240,length*.45))
            measured=shift/sent
            desired=max(12,min(240,target/measured))
            self.auto_rate=self.auto_rate*.7+desired*.3
            if shift>length*.35:self.auto_rate=min(self.auto_rate,desired*.6)
            self.auto_progress_units=units
            self.auto_progress_time=now
            self.auto_failed_time=None
            pump.set_rate(self.auto_rate)
            self.tip.setText('自动滚动中 · 再次点击自动滚动按钮可停止')
        self.auto_last_units=units

    def oriented(self,frame):
        oriented=frame if self.vertical else frame.transpose(1,0,2)
        return oriented[::-1] if self.reverse else oriented

    def restored(self,frame):
        oriented=frame[::-1] if self.reverse else frame
        return oriented if self.vertical else oriented.transpose(1,0,2)

    def tick(self):
        if self.finished or self.paused or not self.started:return
        if self.auto_settling:return
        if self.automatic:
            self.auto_tick()
            return
        # Continue briefly after wheel events to allow smooth scrolling to settle.
        if time.monotonic()-self.last_wheel>1.2:return
        self.append_frame(self.grab())

    def append_frame(self,frame):
        before=self.oriented(self.previous)
        after=self.oriented(frame)
        if self.stitcher is None:self.stitcher=ContentStitcher(before)
        try:shift=self.stitcher.append(after)
        except OverflowError:
            self.stop_auto()
            self.paused=True
            self.tip.setText('已达长度上限，请复制或保存')
            self.refresh_preview()
            return
        if shift is None:
            self.tip.setText('重叠区域不足，请回滚少许后沿所选方向缓慢滚动')
            return None
        if not shift:return 0
        full=self.stitcher.image()
        self.parts=[self.restored(full)]
        self.total=full.shape[0]
        self.previous=frame
        self.tip.setText('正在拼接 · 点击工具栏复制或保存')
        self.refresh_preview()
        return shift

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
            # Drop pixels from the frozen transition cover before switching
            # to a live, alpha-only mask (including on backing-store reuse).
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(self.rect(),Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            if self.transition_cover:
                p.drawPixmap(self.rect(),self.frozen)
                p.fillRect(self.rect(),QColor(0,0,0,105))
                p.save()
                try:
                    p.setClipRect(self.region)
                    p.drawPixmap(self.rect(),self.frozen)
                finally:
                    p.restore()
            else:
                p.fillRect(self.rect(),QColor(0,0,0,80))
            p.setPen(QPen(QColor('#3286ff'),BORDER_WIDTH))
            p.drawRect(self.region)
        if self.transition_cover and not self.transition_scheduled:
            self.transition_scheduled=True
            QTimer.singleShot(0,self.finish_transition)

    def pause(self):
        if self.automatic:self.begin_auto_stop()
        elif not self.auto_settling:self.stop_auto()
        self.paused=not self.paused
        self.pause_action.setIcon(lucide('play' if self.paused else 'pause'))
        self.tip.setText('已暂停，点击继续后在框内滚动' if self.paused else '在蓝框内滚动鼠标继续拼接')
        self.last_wheel=0
        self.refresh_preview()

    def change_direction(self,index):
        self.stop_auto()
        self.stitcher=None
        if self.parts:
            self.previous=self.grab()
            self.parts=[self.previous]
        self.vertical=index in (0,2)
        self.reverse=index in (2,3)
        self.total=self.previous.shape[0 if self.vertical else 1] if self.previous is not None else 0
        self.last_wheel=0
        self.started=False
        self.refresh_preview()

    def complete(self,action):
        if not self.parts or self.finished:return
        if self.automatic:
            self.begin_auto_stop(action=action)
            return
        if self.auto_settling:
            self.settle_action=action
            return
        self.stop_auto()
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
        self.stop_auto()
        if self.transition_callback:
            callback=self.transition_callback
            self.transition_callback=None
            callback()
        self.finished=True
        self.timer.stop()
        self.monitor.stop()
        self.close()

    def closeEvent(self,event):
        self.stop_auto()
        self.finished=True
        self.timer.stop()
        self.monitor.stop()
        event.accept()
