"""Manual scrolling stitcher and local silent screen recording."""
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt,QTimer,QElapsedTimer,QRect
from PySide6.QtGui import QPixmap,QImage
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QPushButton,QFileDialog,QMessageBox


def stitch_shift(previous,current):
    import cv2
    import numpy as np
    if previous.shape!=current.shape:return None
    h,w=previous.shape[:2]
    if h<80 or w<80:return None
    a=cv2.cvtColor(previous,cv2.COLOR_BGR2GRAY)
    b=cv2.cvtColor(current,cv2.COLOR_BGR2GRAY)
    if np.mean(cv2.absdiff(a,b))<1.0:return 0
    x0,x1=int(w*.01),int(w*.97)
    candidates=[]
    # Search forward only; repeated rows must not select a backwards match.
    # Validate several bands against the complete overlap before appending.
    for fraction in (.1,.25,.5):
        y0=int(h*fraction)
        tile=b[y0:y0+int(h*.23),x0:x1]
        if tile.std()<5:continue
        search=a[y0:min(h,y0+int(h*.7)+tile.shape[0]),x0:x1]
        scores=cv2.matchTemplate(search,tile,cv2.TM_CCOEFF_NORMED).ravel()
        for shift in np.argsort(scores)[-4:]:
            shift=int(shift)
            if shift<1 or shift>int(h*.7) or scores[shift]<.94:continue
            difference=np.mean(cv2.absdiff(a[shift:,x0:x1],b[:h-shift,x0:x1]))
            if difference<8:candidates.append((float(difference),shift))
    return min(candidates)[1] if candidates else None


class CaptureSession(QWidget):
    def __init__(self,controller,screen,region,mode):
        super().__init__(None,Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.Tool)
        self.controller,self.screen,self.region,self.mode=controller,screen,QRect(region),mode
        self.setWindowTitle('轻截 · '+('长截图' if mode=='scroll' else '录屏'))
        self.resize(290,180)
        self.previous=None
        self.parts=[]
        self.total_height=0
        self.writer=None
        self.path=None
        self.frames=0
        self.finished=False
        self.elapsed=QElapsedTimer()
        self.elapsed.start()
        l=QVBoxLayout(self)
        self.status=QLabel('请缓慢向下滚动；滚动区域应避开固定顶栏和底栏。' if mode=='scroll' else '静音 MP4 录屏 · 10 fps\n录制期间请保持窗口与分辨率不变。')
        self.status.setWordWrap(True)
        l.addWidget(self.status)
        self.detail=QLabel('正在准备…')
        l.addWidget(self.detail)
        stop=QPushButton('完成长截图' if mode=='scroll' else '停止并保存')
        stop.clicked.connect(self.finish)
        l.addWidget(stop)
        cancel=QPushButton('取消')
        cancel.clicked.connect(self.cancel)
        l.addWidget(cancel)
        self.timer=QTimer(self)
        self.timer.timeout.connect(self.tick)
        # Keep control window outside the capture rectangle when possible.
        global_r=QRect(region.translated(screen.geometry().topLeft()))
        available=screen.availableGeometry()
        x=global_r.right()+15
        y=global_r.top()
        if x+self.width()>available.right():x=global_r.left()-self.width()-15
        if x<available.left():
            others=[s for s in __import__('PySide6.QtWidgets',fromlist=['QApplication']).QApplication.screens() if s!=screen]
            if others:
                point=others[0].availableGeometry().topLeft()
                x,y=point.x()+20,point.y()+20
            else:
                x,y=available.left()+10,available.bottom()-self.height()-10
                self.status.setText(self.status.text()+'\n控制条可能进入画面，可将其拖到选区外。')
        self.move(x,y)

    def grab(self):
        from app import png_bytes
        import cv2
        import numpy as np
        full=self.screen.grabWindow(0)
        sx,sy=full.width()/self.screen.geometry().width(),full.height()/self.screen.geometry().height()
        r=self.region
        pix=full.copy(QRect(round(r.x()*sx),round(r.y()*sy),round(r.width()*sx),round(r.height()*sy)))
        return cv2.imdecode(np.frombuffer(png_bytes(pix),np.uint8),cv2.IMREAD_COLOR)

    def start(self):
        if self.mode=='video':
            path,_=QFileDialog.getSaveFileName(None,'保存静音录屏','轻截录屏-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.mp4','MP4 视频 (*.mp4)')
            if not path:
                self.finished=True
                self.close()
                return
            self.path=path
        self.show()
        self.timer.start(400 if self.mode=='scroll' else 100)
        QTimer.singleShot(150,self.tick)

    def tick(self):
        if self.finished:return
        import cv2
        try:
            frame=self.grab()
            if frame is None:raise RuntimeError('无法读取截图区域。')
            if self.mode=='scroll':
                if self.previous is None:
                    self.parts=[frame]
                    self.previous=frame
                    self.total_height=frame.shape[0]
                else:
                    shift=stitch_shift(self.previous,frame)
                    if shift is None:
                        self.detail.setText('未找到可靠重叠，请向上回滚少许后缓慢向下滚动。')
                        return
                    if shift:
                        if self.total_height+shift>50000:
                            self.finish()
                            return
                        self.parts.append(frame[-shift:].copy())
                        self.total_height+=shift
                        self.previous=frame
                self.detail.setText(f'已拼接 {self.total_height} px · {len(self.parts)} 段')
            else:
                h,w=frame.shape[:2]
                frame=frame[:h-h%2,:w-w%2]
                if self.writer is None:
                    self.writer=cv2.VideoWriter(self.path,cv2.VideoWriter_fourcc(*'mp4v'),10,(frame.shape[1],frame.shape[0]))
                    if not self.writer.isOpened():raise RuntimeError('无法创建 MP4 编码器或写入文件。')
                self.writer.write(frame)
                self.frames+=1
                self.detail.setText(f'已录制 {self.frames/10:.1f} 秒 · 静音')
        except Exception as exc:
            self.timer.stop()
            self.status.setText('操作失败：'+str(exc))

    def finish(self):
        if self.finished:return
        self.finished=True
        self.timer.stop()
        if self.writer:
            self.writer.release()
            self.writer=None
            self.controller.tray.showMessage('轻截','录屏已保存：'+str(self.path))
        elif self.mode=='scroll' and self.parts:
            import cv2
            import numpy as np
            full=np.concatenate(self.parts,axis=0)
            rgb=cv2.cvtColor(full,cv2.COLOR_BGR2RGB)
            img=QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format.Format_RGB888).copy()
            self.controller.edit(QPixmap.fromImage(img))
        self.close()

    def cancel(self):
        self.finished=True
        self.timer.stop()
        if self.writer:
            self.writer.release()
            self.writer=None
        # A partially recorded file is retained; the user can remove it.
        self.close()

    def closeEvent(self,event):
        self.timer.stop()
        if self.writer:self.writer.release()
        self.writer=None
        self.finished=True
        event.accept()
