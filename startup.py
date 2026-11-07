"""Current-user Windows sign-in startup for the portable application."""
from pathlib import Path
import subprocess
import sys
import winreg

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'LightSnip'


def startup_command():
    executable = Path(sys.executable).resolve()
    if getattr(sys, 'frozen', False):
        args = [str(executable)]
    else:
        pythonw = executable.with_name('pythonw.exe')
        args = [str(pythonw if pythonw.exists() else executable),
                str(Path(__file__).resolve().with_name('app.py'))]
    return subprocess.list2cmdline(args + ['--autostart'])


def registered_command():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except FileNotFoundError:
        return ''


def is_enabled():
    return bool(registered_command())


def set_enabled(enabled):
    desired = startup_command() if enabled else ''
    if registered_command() == desired:
        return
    if enabled:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, desired)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
