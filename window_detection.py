"""Visible top-level window bounds captured before screenshot overlays appear."""
import ctypes
import sys
from dataclasses import dataclass
from PySide6.QtCore import QPoint,QRect


@dataclass
class ScreenMapping:
    name:str
    logical:QRect
    native:QRect

    def native_point(self,point):
        return QPoint(self.native.x()+round((point.x()-self.logical.x())*self.native.width()/self.logical.width()),
                      self.native.y()+round((point.y()-self.logical.y())*self.native.height()/self.logical.height()))

    def logical_rect(self,rect):
        piece=rect.intersected(self.native)
        if piece.isEmpty():return QRect()
        x=self.logical.x()+round((piece.x()-self.native.x())*self.logical.width()/self.native.width())
        y=self.logical.y()+round((piece.y()-self.native.y())*self.logical.height()/self.native.height())
        right=self.logical.x()+round((piece.x()+piece.width()-self.native.x())*self.logical.width()/self.native.width())
        bottom=self.logical.y()+round((piece.y()+piece.height()-self.native.y())*self.logical.height()/self.native.height())
        return QRect(x,y,right-x,bottom-y).intersected(self.logical)

    def frozen_rect(self,rect,size):
        piece=rect.intersected(self.native)
        return QRect(round((piece.x()-self.native.x())*size.width()/self.native.width()),
                     round((piece.y()-self.native.y())*size.height()/self.native.height()),
                     round(piece.width()*size.width()/self.native.width()),
                     round(piece.height()*size.height()/self.native.height()))


@dataclass
class WindowTarget:
    handle:int
    logical:QRect
    native:QRect
    mapping:ScreenMapping
    kind:str='window'


class WindowCatalog:
    def __init__(self,mappings=(),windows=()):
        self.mappings=list(mappings)
        self.windows=list(windows)
        self.regions={}

    def candidates_at(self,point,screen=None):
        mapping=next((item for item in self.mappings if item.logical.contains(point)),None)
        if mapping is None:return []
        native=mapping.native_point(point)
        for handle,rect in self.windows:
            if rect.contains(native):
                piece=rect.intersected(mapping.native)
                found={}
                for kind,region in self.regions.get(handle,[]):
                    region=region.intersected(piece)
                    if region.width()>=5 and region.height()>=5 and region.contains(native):
                        found.setdefault(region.getRect(),(kind,region))
                found[piece.getRect()]=('window',piece)
                ordered=sorted(found.values(),key=lambda entry:entry[1].width()*entry[1].height())
                control=next((entry for entry in ordered if entry[0]=='control' and entry[1].width()*entry[1].height()<piece.width()*piece.height()*.6),None)
                if control is not None:
                    ordered=[entry for entry in ordered if entry[1].adjusted(-2,-2,2,2).contains(control[1])]
                chain=[]
                for kind,region in ordered:
                    # Only ancestors of the smallest hit belong to this path.
                    if chain and not region.adjusted(-2,-2,2,2).contains(chain[-1].native):continue
                    logical=mapping.logical_rect(region)
                    if logical.width()>=3 and logical.height()>=3:
                        chain.append(WindowTarget(handle,logical,region,mapping,kind))
                return chain
        return []

    def target_at(self,point,screen=None,level=0):
        targets=self.candidates_at(point,screen)
        return targets[min(max(0,level),len(targets)-1)] if targets else None

    def add_regions(self,handle,regions):
        self.regions.setdefault(handle,[]).extend(regions)


def _native_state():
    if sys.platform!='win32':return {},[]
    from ctypes import wintypes
    user=ctypes.WinDLL('user32',use_last_error=True)
    try:dwm=ctypes.WinDLL('dwmapi')
    except OSError:dwm=None
    user.IsWindowVisible.argtypes=[wintypes.HWND]
    user.IsIconic.argtypes=[wintypes.HWND]
    user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user.GetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int]
    user.GetWindowLongW.restype=wintypes.LONG
    if dwm:
        dwm.DwmGetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
        dwm.DwmGetWindowAttribute.restype=ctypes.c_long
    class MonitorInfo(ctypes.Structure):
        _fields_=[('cbSize',wintypes.DWORD),('rcMonitor',wintypes.RECT),('rcWork',wintypes.RECT),('dwFlags',wintypes.DWORD),('szDevice',wintypes.WCHAR*32)]
    monitor_callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HANDLE,wintypes.HDC,ctypes.POINTER(wintypes.RECT),wintypes.LPARAM)
    user.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(MonitorInfo)]
    user.EnumDisplayMonitors.argtypes=[wintypes.HDC,ctypes.c_void_p,monitor_callback,wintypes.LPARAM]
    monitors={}
    @monitor_callback
    def visit_monitor(handle,dc,rect,data):
        info=MonitorInfo()
        info.cbSize=ctypes.sizeof(info)
        if user.GetMonitorInfoW(handle,ctypes.byref(info)):
            r=info.rcMonitor
            monitors[info.szDevice.casefold()]=QRect(r.left,r.top,r.right-r.left,r.bottom-r.top)
        return True
    user.EnumDisplayMonitors(None,None,visit_monitor,0)
    window_callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.EnumWindows.argtypes=[window_callback,wintypes.LPARAM]
    windows=[]
    @window_callback
    def visit_window(handle,data):
        if not user.IsWindowVisible(handle) or user.IsIconic(handle):return True
        if user.GetWindowLongW(handle,-20)&0x20:return True  # click-through overlays
        name=ctypes.create_unicode_buffer(256)
        user.GetClassNameW(handle,name,len(name))
        if name.value in {'Progman','WorkerW','Shell_TrayWnd','Shell_SecondaryTrayWnd','tooltips_class32'}:return True
        if dwm:
            cloaked=wintypes.DWORD()
            if dwm.DwmGetWindowAttribute(handle,14,ctypes.byref(cloaked),ctypes.sizeof(cloaked))==0 and cloaked.value:return True
        rect=wintypes.RECT()
        found=dwm and dwm.DwmGetWindowAttribute(handle,9,ctypes.byref(rect),ctypes.sizeof(rect))==0
        if not found and not user.GetWindowRect(handle,ctypes.byref(rect)):return True
        r=QRect(rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top)
        if r.width()>=40 and r.height()>=30:windows.append((int(handle),r))
        return True
    user.EnumWindows(visit_window,0)
    return monitors,windows


def snapshot_windows(screens):
    try:monitors,windows=_native_state()
    except (OSError,AttributeError):monitors,windows={},[]
    mappings=[]
    for screen in screens:
        logical=QRect(screen.geometry())
        native=monitors.get(screen.name().casefold())
        if native is None:
            ratio=screen.devicePixelRatio()
            expected=QRect(logical.x(),logical.y(),round(logical.width()*ratio),round(logical.height()*ratio))
            native=next((rect for rect in monitors.values() if rect.topLeft()==expected.topLeft() and abs(rect.width()-expected.width())<=3 and abs(rect.height()-expected.height())<=3),expected)
        mappings.append(ScreenMapping(screen.name(),logical,native))
    return WindowCatalog(mappings,windows)
