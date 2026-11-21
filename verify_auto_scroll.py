"""Native two-process wheel + region capture verification on a synthetic page."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from PySide6.QtCore import Qt,QRect,QTimer,QPoint,QSize,QEventLoop
from PySide6.QtGui import QPainter,QCursor
from PySide6.QtWidgets import QApplication,QWidget
from scroll_capture import ScrollCapture,array_pixmap

VIEW=int(os.environ.get('LIGHTSNIP_VERIFY_VIEW','320'))

def document():
    return np.random.default_rng(991).integers(0,256,(VIEW*3,VIEW,3),dtype=np.uint8)


def wait(milliseconds):
    # Use the real Qt event loop. QTest.qWait keeps the Python GIL on this
    # PySide build and would artificially starve the continuous wheel thread.
    loop=QEventLoop()
    QTimer.singleShot(milliseconds,loop.quit)
    loop.exec()


def target(ready_path,index):
    application=QApplication([])
    class Page(QWidget):
        def __init__(self):
            super().__init__(None,Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.content=document()
            self.offset=VIEW*2 if index in (2,3) else 0
            self.desired=self.offset
            self.wheels=[]
            self.paints=[]
            screen=application.primaryScreen()
            self.setGeometry(QRect(screen.availableGeometry().center()-QPoint(VIEW//2,(VIEW+120)//2),QSize(VIEW,VIEW+120)))
            self.animation=QTimer(self)
            self.animation.setInterval(16)
            self.animation.timeout.connect(self.animate_scroll)
            self.animation.start()
        def wheelEvent(self,event):
            delta=event.angleDelta().y() if index in (0,2) else event.angleDelta().x()
            self.desired=max(0,min(VIEW*2,self.desired-delta))
            self.wheels.append((time.monotonic(),abs(delta)))
            event.accept()
        def animate_scroll(self):
            distance=self.desired-self.offset
            if distance:
                self.offset+=(1 if distance>0 else -1)*max(1,round(abs(distance)*.35))
                self.update()
        def paintEvent(self,event):
            with QPainter(self) as painter:
                frame=self.content[self.offset:self.offset+VIEW]
                if index in (1,3):frame=frame.transpose(1,0,2)
                painter.drawPixmap(0,0,array_pixmap(frame))
            if not self.paints or self.paints[-1][1]!=self.offset:
                self.paints.append((time.monotonic(),self.offset))
    page=Page()
    page.show()
    def ready():
        r=page.geometry()
        ready_path.write_text(json.dumps([r.x(),r.y(),r.width(),VIEW]),encoding='utf-8')
    QTimer.singleShot(250,ready)
    stats_timer=QTimer(page)
    stats_timer.setInterval(150)
    stats_timer.timeout.connect(lambda:ready_path.with_suffix('.events.json').write_text(json.dumps({'wheels':page.wheels,'paints':page.paints}),encoding='utf-8'))
    stats_timer.start()
    QTimer.singleShot(45000,application.quit)
    application.exec()


def verify(output,index=0):
    application=QApplication.instance() or QApplication([])
    output.parent.mkdir(parents=True,exist_ok=True)
    ready=output.with_suffix('.ready.json')
    ready.unlink(missing_ok=True)
    ready.with_suffix('.events.json').unlink(missing_ok=True)
    child=subprocess.Popen([sys.executable,__file__,'--target',str(ready),str(index)],creationflags=subprocess.CREATE_NO_WINDOW)
    capture=None
    cursor=QCursor.pos()
    try:
        deadline=time.monotonic()+10
        while not ready.exists() and time.monotonic()<deadline:wait(50)
        assert ready.exists(),'测试页面未启动'
        r=QRect(*json.loads(ready.read_text(encoding='utf-8')))
        screen=application.screenAt(r.center())
        region=r.translated(-screen.geometry().topLeft())
        QCursor.setPos(screen.geometry().topLeft()+QPoint(15,15))
        frozen=screen.grabWindow(0)
        capture=ScrollCapture(None,screen,region,frozen)
        capture.direction.setCurrentIndex(index)
        capture.start()
        wait(150)
        cursor_before=QCursor.pos()
        capture.toggle_auto()
        deadline=time.monotonic()+25
        while (capture.automatic or capture.auto_settling) and time.monotonic()<deadline:wait(50)
        assert not capture.automatic,'自动滚动未停止'
        wait(250)
        result=capture.full_frame()
        expected=document() if index in (0,2) else document().transpose(1,0,2)
        np.testing.assert_array_equal(result,expected)
        assert '不再滚动' in capture.tip.text(),capture.tip.text()
        events=json.loads(ready.with_suffix('.events.json').read_text(encoding='utf-8'))
        paints=np.array(events['paints'])
        paint_intervals=np.diff(paints[:,0])*1000
        median_ms=float(np.median(paint_intervals))
        assert len(paints)>=25,('页面没有连续重绘',len(paints))
        assert median_ms<100,('滚动重绘仍有明显停顿',median_ms)
        output.write_text(json.dumps({'native_wheel':True,'whole_document':True,'cursor_unchanged':QCursor.pos()==cursor_before,'auto_stop':True,'direction':index,'size':[result.shape[1],result.shape[0]],'moving_frames':len(paints),'median_frame_ms':round(median_ms,2),'max_wheel_step':max(event[1] for event in events['wheels']),'ok':True}),encoding='utf-8')
    finally:
        if capture is not None:capture.cancel()
        child.terminate()
        child.wait(timeout=5)
        QCursor.setPos(cursor)


if __name__=='__main__':
    if sys.argv[1]=='--target':target(Path(sys.argv[2]),int(sys.argv[3]))
    else:verify(Path(sys.argv[1]),int(sys.argv[2]) if len(sys.argv)>2 else 0)
