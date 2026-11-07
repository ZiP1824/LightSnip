"""Local, bounded control snapshots and visual text regions for capture previews."""
import multiprocessing
import sys
import threading
from pathlib import Path
from PySide6.QtCore import QObject,Signal,QRunnable,QThreadPool,QRect,QBuffer,QIODevice


def _control_worker(handle,connection):
    try:
        import comtypes
        import comtypes.client
        # Wrappers are generated during setup/build and shipped with the app.
        from comtypes.gen import UIAutomationClient as uia
        automation=comtypes.client.CreateObject(uia.CUIAutomation8,interface=uia.IUIAutomation2)
        automation.ConnectionTimeout=350
        automation.TransactionTimeout=600
        cache=automation.CreateCacheRequest()
        for prop in [uia.UIA_BoundingRectanglePropertyId,uia.UIA_IsOffscreenPropertyId,uia.UIA_ControlTypePropertyId]:cache.AddProperty(prop)
        root=automation.ElementFromHandle(handle)
        elements=root.FindAllBuildCache(uia.TreeScope_Descendants,automation.CreateTrueCondition(),cache)
        regions=[]
        for index in range(min(elements.Length,2500)):
            item=elements.GetElement(index)
            try:
                if item.CachedIsOffscreen:continue
                r=item.CachedBoundingRectangle
                if r.right-r.left>=5 and r.bottom-r.top>=5:
                    regions.append((r.left,r.top,r.right-r.left,r.bottom-r.top,item.CachedControlType))
            except (comtypes.COMError,OSError):continue
        connection.send(regions)
    except Exception:
        try:connection.send([])
        except (OSError,BrokenPipeError):pass
    finally:connection.close()


def control_regions(handle,timeout=2.8):
    if sys.platform!='win32':return []
    context=multiprocessing.get_context('spawn')
    receiver,sender=context.Pipe(duplex=False)
    process=context.Process(target=_control_worker,args=(handle,sender),daemon=True)
    try:
        process.start()
        sender.close()
        return receiver.recv() if receiver.poll(timeout) else []
    except (OSError,EOFError):return []
    finally:
        sender.close()
        receiver.close()
        if process.pid:
            process.join(.05)
            if process.is_alive():process.terminate();process.join(.5)
            if not process.is_alive():process.close()


def text_regions(boxes,bounds):
    """Join same-line fragments and adjacent wrapped lines without joining columns."""
    rows=[]
    for box in sorted(boxes,key=lambda r:(r.center().y(),r.left())):
        if box.width()<5 or box.height()<5:continue
        match=next((r for r in reversed(rows[-8:]) if abs(r.center().y()-box.center().y())<min(r.height(),box.height())*.45
                    and max(r.height(),box.height())<min(r.height(),box.height())*1.5
                    and -3<=box.left()-r.right()<=max(r.height(),box.height())*1.8),None)
        if match is not None:match|=box
        else:rows.append(QRect(box))
    rows.sort(key=lambda r:(r.top(),r.left()))
    groups=[]
    for row in rows:
        candidates=[]
        for group in groups:
            last=group[-1]
            height=min(row.height(),last.height())
            overlap=min(row.right(),last.right())-max(row.left(),last.left())
            gap=row.top()-last.bottom()-1
            if 0<=gap<=height*.85 and max(row.height(),last.height())<=height*1.35 and overlap>=min(row.width(),last.width())*.4 and abs(row.left()-last.left())<height*1.8:
                candidates.append((gap,group))
        if candidates:min(candidates,key=lambda c:c[0])[1].append(row)
        else:groups.append([row])
    result=[]
    for row in rows:
        margin=max(3,round(row.height()*.15))
        result.append(('line',row.adjusted(-margin,-margin,margin,margin).intersected(bounds)))
    for group in groups:
        if len(group)<2:continue
        rect=QRect(group[0])
        for row in group[1:]:rect|=row
        result.append(('paragraph',rect.adjusted(-5,-5,5,5).intersected(bounds)))
    return result


_detector=None
_detector_lock=threading.Lock()


def detect_text_regions(data):
    global _detector
    import cv2
    import numpy as np
    import rapidocr_onnxruntime
    from rapidocr_onnxruntime.ch_ppocr_v3_det.text_detect import TextDetector
    from rapidocr_onnxruntime.utils import read_yaml,concat_model_path
    image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
    if image is None or image.std()<2:return []
    with _detector_lock:
        if _detector is None:
            config=concat_model_path(read_yaml(Path(rapidocr_onnxruntime.__file__).parent/'config.yaml'))['Det']
            config.update(limit_side_len=1600,limit_type='max')
            _detector=TextDetector(config)
        boxes,_=_detector(image)
    if boxes is None:return []
    rects=[]
    for box in boxes:
        x,y=box[:,0],box[:,1]
        rects.append(QRect(round(float(x.min())),round(float(y.min())),round(float(x.max()-x.min()))+1,round(float(y.max()-y.min()))+1))
    return text_regions(rects,QRect(0,0,image.shape[1],image.shape[0]))


class ScanSignals(QObject):
    ready=Signal(object,object)


class ScanJob(QRunnable):
    def __init__(self,handle,work,signals,cancel):
        super().__init__()
        self.handle,self.work,self.signals,self.cancel=handle,work,signals,cancel

    def run(self):
        try:regions=[] if self.cancel.is_set() else self.work()
        except Exception:regions=[]
        try:self.signals.ready.emit(self.handle,regions)
        except RuntimeError:pass  # The application may have closed meanwhile.


class RegionScanner(QObject):
    def __init__(self,catalog,parent=None):
        super().__init__(parent)
        self.catalog=catalog
        self.pending=set()
        self.controls_pending=set()
        self.active_jobs=0
        self.cancel=threading.Event()
        self.signals=ScanSignals(self)
        self.signals.ready.connect(self.accept)

    def ensure(self,target,frozen):
        key=(target.handle,target.mapping.name)
        if self.cancel.is_set() or key in self.pending or len(self.pending)>=8:return
        self.pending.add(key)
        handle=target.handle
        # UIA metadata comes from the original HWND, never the capture overlay.
        if handle not in self.controls_pending:
            self.controls_pending.add(handle)
            meaningful={50000,50002,50003,50004,50005,50006,50007,50011,50013,50015,50016,50019,50024,50029}
            control=ScanJob(handle,lambda:[('control' if r[4] in meaningful else 'text' if r[4]==50020 else 'pane',QRect(*r[:4])) for r in control_regions(handle)],self.signals,self.cancel)
            self.active_jobs+=1
            QThreadPool.globalInstance().start(control)
        root=next((r for h,r in self.catalog.windows if h==handle),target.native)
        native=root.intersected(target.mapping.native)
        pix=frozen.copy(target.mapping.frozen_rect(native,frozen.size()))
        buffer=QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pix.save(buffer,'PNG')
        data=bytes(buffer.data())
        sx,sy=native.width()/pix.width(),native.height()/pix.height()
        def visual():
            return [(kind,QRect(native.x()+round(r.x()*sx),native.y()+round(r.y()*sy),round(r.width()*sx),round(r.height()*sy))) for kind,r in detect_text_regions(data)]
        self.active_jobs+=1
        QThreadPool.globalInstance().start(ScanJob(handle,visual,self.signals,self.cancel))

    def accept(self,handle,regions):
        self.active_jobs-=1
        if not self.cancel.is_set():self.catalog.add_regions(handle,regions)
        elif self.active_jobs==0:self.deleteLater()

    def stop(self):
        self.cancel.set()
        if self.active_jobs==0:self.deleteLater()
