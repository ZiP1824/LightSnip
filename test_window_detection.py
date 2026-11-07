import ctypes
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QPoint,QPointF,QRect,QSize,QSettings,QEvent,QCoreApplication
from PySide6.QtGui import QPixmap,QColor,QMouseEvent,QKeySequence
from PySide6.QtTest import QTest
from window_detection import ScreenMapping,WindowCatalog
from app import Overlay,Home,Hotkeys
from settings_ui import SettingsWindow,keys

app=QApplication.instance() or QApplication([])


class WindowDetectionChecks(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.cfg=QSettings(str(Path(self.directory.name)/'preferences.ini'),QSettings.Format.IniFormat)
        self.settings_patch=patch('settings_ui.preferences',return_value=self.cfg)
        self.app_patch=patch('app.preferences',return_value=self.cfg)
        self.settings_patch.start()
        self.app_patch.start()

    def tearDown(self):
        for widget in app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.app_patch.stop()
        self.settings_patch.stop()
        self.directory.cleanup()

    def overlay(self):
        screen=app.primaryScreen()
        logical=QRect(screen.geometry())
        native=QRect(logical.x(),logical.y(),logical.width()*2,logical.height()*2)
        mapping=ScreenMapping(screen.name(),logical,native)
        window=QRect(native.x()+200,native.y()+160,800,500)
        catalog=WindowCatalog([mapping],[(17,window)])
        frozen=QPixmap(logical.size()*2)
        frozen.fill(QColor('#74b1df'))
        overlay=Overlay(screen,frozen,window_catalog=catalog)
        overlay.set_capture_active(True,logical.topLeft()+QPoint(250,160))
        return overlay

    def test_front_window_wins_and_desktop_has_no_target(self):
        mapping=ScreenMapping('test',QRect(0,0,1200,800),QRect(0,0,1200,800))
        catalog=WindowCatalog([mapping],[(2,QRect(200,150,300,200)),(1,QRect(50,50,900,650))])
        self.assertEqual(catalog.target_at(QPoint(250,200)).handle,2)
        self.assertEqual(catalog.target_at(QPoint(100,100)).handle,1)
        self.assertIsNone(catalog.target_at(QPoint(1100,700)))

    def test_negative_monitor_coordinates_and_scaled_native_pixels(self):
        mapping=ScreenMapping('left',QRect(-1920,0,1280,720),QRect(-1920,0,1920,1080))
        target=WindowCatalog([mapping],[(7,QRect(-1800,150,600,450))]).target_at(QPoint(-1700,200))
        self.assertEqual(target.logical,QRect(-1840,100,400,300))
        self.assertEqual(mapping.frozen_rect(target.native,QSize(1920,1080)),QRect(120,150,600,450))

    def test_hover_and_click_select_the_complete_visible_window(self):
        overlay=self.overlay()
        self.assertIsNotNone(overlay.hover_target)
        self.assertIsNone(overlay.canvas)
        QTest.mouseClick(overlay,Qt.MouseButton.LeftButton,pos=QPoint(250,160))
        self.assertEqual(overlay.rect_selected,QRect(100,80,400,250))
        self.assertEqual(overlay.canvas.pixmap().size(),QSize(800,500))

    def test_drag_overrides_window_prediction(self):
        overlay=self.overlay()
        QTest.mousePress(overlay,Qt.MouseButton.LeftButton,pos=QPoint(200,150))
        event=QMouseEvent(QEvent.Type.MouseMove,QPointF(360,240),QPointF(overlay.mapToGlobal(QPoint(360,240))),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        app.sendEvent(overlay,event)
        QTest.mouseRelease(overlay,Qt.MouseButton.LeftButton,pos=QPoint(360,240))
        self.assertEqual(overlay.rect_selected,QRect(QPoint(200,150),QPoint(360,240)))
        self.assertIsNone(overlay.hover_target)

    def test_copy_can_confirm_a_hovered_window_without_manual_drag(self):
        overlay=self.overlay()
        images=[]
        overlay.selected.connect(images.append)
        overlay.finish()
        self.assertEqual(len(images),1)
        self.assertEqual(images[0].size(),QSize(800,500))

    def test_configurable_toggle_updates_hint_and_keeps_existing_selection(self):
        self.cfg.setValue('keys/8','F9')
        overlay=self.overlay()
        overlay.show()
        self.assertEqual(overlay.detection_hint_key.text(),'F9')
        QTest.keyClick(overlay,Qt.Key.Key_F9)
        self.assertFalse(overlay.window_detection)
        self.assertIsNone(overlay.hover_target)
        self.assertIn('关',overlay.detection_hint_state.text())
        QTest.keyClick(overlay,Qt.Key.Key_F9)
        self.assertTrue(overlay.window_detection)
        QTest.mouseClick(overlay,Qt.MouseButton.LeftButton,pos=QPoint(250,160))
        canvas=overlay.canvas
        QTest.keyClick(overlay,Qt.Key.Key_F9)
        self.assertIs(overlay.canvas,canvas)
        self.assertEqual(overlay.rect_selected,QRect(100,80,400,250))

    def test_capture_only_binding_does_not_register_globally_at_startup(self):
        with patch('app.ctypes.windll.user32.RegisterHotKey',return_value=1) as register:
            hotkeys=Hotkeys(None)
        self.assertNotIn(8,hotkeys.registered)
        self.assertEqual(hotkeys.current[8],'F8')
        self.assertFalse(any(call.args[1]==8 for call in register.call_args_list))

    def test_native_registered_toggle_is_not_repeated_by_local_key_event(self):
        overlay=self.overlay()
        toggle=MagicMock()
        overlay.controller=SimpleNamespace(hotkeys=SimpleNamespace(registered=[101]),toggle_window_detection=toggle)
        overlay.show()
        QTest.keyClick(overlay,Qt.Key.Key_F8)
        toggle.assert_not_called()

    def test_reserved_capture_shortcuts_are_rejected(self):
        with patch('app.keys',return_value={}):hotkeys=Hotkeys(None)
        for sequence in ['Ctrl+C','L','Esc']:
            ok,message=hotkeys.rebind({8:sequence})
            self.assertFalse(ok)
            self.assertIn('冲突',message)

    def test_native_toggle_only_exists_during_capture(self):
        from ctypes.wintypes import MSG
        controller=SimpleNamespace(toggle_window_detection=MagicMock())
        with patch('app.keys',return_value={}):hotkeys=Hotkeys(controller)
        with patch('app.ctypes.windll.user32.RegisterHotKey',return_value=1) as register,patch('app.ctypes.windll.user32.UnregisterHotKey') as unregister:
            hotkeys.start_capture_copy('F8')
            register.assert_any_call(None,101,0x4000,0x77)
            message=MSG()
            message.message=0x0312
            message.wParam=101
            self.assertEqual(hotkeys.nativeEventFilter(None,ctypes.addressof(message)),(True,0))
            QTest.qWait(1)
            controller.toggle_window_detection.assert_called_once()
            hotkeys.stop_capture_copy()
            self.assertEqual(hotkeys.registered,[])
            unregister.assert_any_call(None,100)
            unregister.assert_any_call(None,101)

    def test_settings_switch_hotkey_and_runtime_state_share_one_value(self):
        controller=SimpleNamespace(overlays=[self.overlay()],settings_window=None)
        controller.capture=MagicMock()
        controller.hotkeys=MagicMock()
        controller.hotkeys.rebind.return_value=(True,'')
        controller.rebuild_tray=MagicMock()
        controller.set_window_detection=lambda value:Home.set_window_detection(controller,value)
        with patch('settings_ui.startup.is_enabled',return_value=False),patch('settings_ui.startup.set_enabled'):
            window=SettingsWindow(controller)
            controller.settings_window=window
            self.assertIn('capture/window_detection',window.bindings)
            self.assertIn(8,window.key_edits)
            Home.toggle_window_detection(controller)
            self.assertFalse(controller.overlays[0].window_detection)
            self.assertFalse(window.bindings['capture/window_detection'][0].isChecked())
            window.key_edits[8].setKeySequence(QKeySequence('F9'))
            window.bindings['capture/window_detection'][0].setChecked(True)
            window.apply()
            self.assertTrue(controller.overlays[0].window_detection)
            self.assertEqual(controller.overlays[0].detection_hint_key.text(),'F9')


if __name__=='__main__':unittest.main()
