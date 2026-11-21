"""Check native live dimming outside a crop while the whole page scrolls."""
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from PySide6.QtCore import Qt,QRect,QPoint,QSize,QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication,QWidget
from scroll_capture import ScrollCapture,array_pixmap,image_array
from verify_auto_scroll import wait


def document():return np.random.default_rng(107).integers(0,256,(960,640,3),dtype=np.uint8)


def target(ready):
    app=QApplication([])
    class Page(QWidget):
        def __init__(self):
            super().__init__(None,Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.offset=0
            self.image=document()
            self.setGeometry(QRect(app.primaryScreen().availableGeometry().center()-QPoint(320,220),QSize(640,440)))
        def wheelEvent(self,event):
            self.offset=max(0,min(640,self.offset-event.angleDelta().y()))
            self.update()
            event.accept()
        def paintEvent(self,event):
            with QPainter(self) as painter:
                painter.drawPixmap(0,0,array_pixmap(self.image[self.offset:self.offset+320]))
    page=Page()
    page.show()
    def publish():
        path=ready.with_suffix('.tmp')
        r=page.geometry()
        path.write_text(json.dumps({'rect':[r.x(),r.y(),r.width(),320],'offset':page.offset}),encoding='utf-8')
        path.replace(ready)
    timer=QTimer(page)
    timer.setInterval(40)
    timer.timeout.connect(publish)
    timer.start()
    QTimer.singleShot(30000,app.quit)
    app.exec()


def verify(output):
    app=QApplication.instance() or QApplication([])
    output.parent.mkdir(parents=True,exist_ok=True)
    ready=output.with_suffix('.ready.json')
    ready.unlink(missing_ok=True)
    child=subprocess.Popen([sys.executable,__file__,'--target',str(ready)],creationflags=subprocess.CREATE_NO_WINDOW)
    capture=None
    try:
        deadline=time.monotonic()+10
        while not ready.exists() and time.monotonic()<deadline:wait(40)
        assert ready.exists(),'测试页面未启动'
        rect=QRect(*json.loads(ready.read_text())['rect'])
        screen=app.screenAt(rect.center())
        region=QRect(rect.x()+160,rect.y(),320,320).translated(-screen.geometry().topLeft())
        frozen=screen.grabWindow(0)
        capture=ScrollCapture(None,screen,region,frozen)
        capture.start(initial_pixmap=frozen.copy(region))
        deadline=time.monotonic()+3
        while capture.transition_cover and time.monotonic()<deadline:wait(20)
        assert not capture.transition_cover,'实时遮罩切换失败'
        capture.toggle_auto()
        deadline=time.monotonic()+10
        while capture.automatic and capture.total<500 and time.monotonic()<deadline:wait(40)
        assert capture.automatic,capture.tip.text()
        capture.pause()
        while capture.auto_settling and time.monotonic()<deadline:wait(40)
        wait(100)
        offset=json.loads(ready.read_text())['offset']
        assert offset>100,offset
        screen_image=image_array(screen.grabWindow(0))
        sx=screen_image.shape[1]/screen.geometry().width()
        sy=screen_image.shape[0]/screen.geometry().height()
        image=document()
        outside=[]
        for y in (80,160,240):
            # Far from the toolbar, border, tip and preview, but under the mask.
            point=QPoint(rect.x()+80,rect.y()+y)-screen.geometry().topLeft()
            actual=screen_image[round(point.y()*sy),round(point.x()*sx)].astype(float)
            expected=np.round(image[offset+y,80].astype(float)*175/255)
            np.testing.assert_allclose(actual,expected,atol=3)
            outside.append(actual.tolist())
        # The selected image is not dimmed, and only selected columns are saved.
        point=region.center()
        actual=screen_image[round(point.y()*sy),round(point.x()*sx)]
        np.testing.assert_array_equal(actual,image[offset+point.y()-region.y(),160+point.x()-region.x()])
        np.testing.assert_array_equal(capture.full_frame(),image[:320+offset,160:480])
        output.write_text(json.dumps({'outside_live_and_dimmed':True,'selected_region_undimmed':True,'crop_only_stitched':True,'transition':True,'offset':offset,'size':[capture.full_frame().shape[1],capture.full_frame().shape[0]],'outside_samples':outside,'ok':True}),encoding='utf-8')
    finally:
        if capture is not None:capture.cancel()
        child.terminate()
        child.wait(timeout=5)


if __name__=='__main__':
    if sys.argv[1]=='--target':target(Path(sys.argv[2]))
    else:verify(Path(sys.argv[1]))
