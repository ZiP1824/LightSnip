"""Timestamped export names and exclusive creation for automatic screenshots."""
from datetime import datetime,timedelta
from pathlib import Path
from threading import Lock
from PySide6.QtCore import QObject,Signal,QCoreApplication

_lock=Lock()
_last_time=None
_location_events=None


class SaveLocationEvents(QObject):
    changed=Signal(str)


def save_location_events():
    global _location_events
    if _location_events is None:_location_events=SaveLocationEvents(QCoreApplication.instance())
    return _location_events


def default_save_directory():
    from PySide6.QtCore import QStandardPaths
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation) or str(Path.home()))


def save_directory():
    from settings_ui import preferences
    value=str(preferences().value('save/path','')).strip()
    return Path(value).expanduser().resolve() if value else default_save_directory()


def choose_save_path(parent,title,prefix='轻截'):
    from PySide6.QtWidgets import QFileDialog
    directory=save_directory()
    # A removed/unavailable folder falls back to the nearest existing parent.
    while not directory.is_dir() and directory.parent!=directory:directory=directory.parent
    suggested=directory/capture_filename(prefix,directory=directory)
    path,_=QFileDialog.getSaveFileName(parent,title,str(suggested),'PNG 图片 (*.png)')
    return path


def remember_saved_file(path):
    set_save_directory(Path(path).expanduser().resolve().parent)


def set_save_directory(directory):
    from settings_ui import preferences
    directory=str(Path(directory).expanduser().resolve())
    cfg=preferences()
    cfg.setValue('save/path',directory)
    cfg.sync()
    save_location_events().changed.emit(directory)


def capture_filename(prefix='轻截',extension='.png',directory=None):
    global _last_time
    with _lock:
        moment=datetime.now()
        if _last_time is not None and moment<=_last_time:
            moment=_last_time+timedelta(microseconds=1)
        while True:
            name=f'{prefix}-{moment:%Y%m%d-%H%M%S-%f}{extension}'
            if directory is None or not (Path(directory)/name).exists():break
            moment+=timedelta(microseconds=1)
        _last_time=moment
        return name


def save_new_png(pixmap,directory,prefix='轻截'):
    from PySide6.QtCore import QBuffer,QIODevice
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    buffer=QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not pixmap.save(buffer,'PNG'):raise OSError('无法编码截图图片。')
    payload=bytes(buffer.data())
    while True:
        path=directory/capture_filename(prefix,directory=directory)
        try:
            with path.open('xb') as stream:stream.write(payload)
            return path
        except FileExistsError:
            # Another process can create the same name after the existence
            # check. Exclusive creation ensures its screenshot stays intact.
            continue
