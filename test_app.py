import io
import json
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QColor, QPainter, QFont
from PySide6.QtCore import QPoint
from services import split_utf8, translate, recognize
from app import Canvas, png_bytes, Editor, TextDialog, OcrDialog, Overlay, Pin
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication([])


class Checks(unittest.TestCase):
    def tearDown(self):
        # Dispose native windows while Qt is still alive, including hidden
        # canvases and menus, instead of leaving them to Python shutdown.
        from PySide6.QtCore import QCoreApplication, QEvent
        for widget in app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_multibyte_chunks(self):
        text = '中文🙂 English\n' * 150
        chunks = split_utf8(text)
        self.assertEqual(''.join(chunks), text)
        self.assertTrue(all(len(c.encode('utf8')) <= 480 for c in chunks))

    def test_text_translation_still_works_without_a_configuration_page(self):
        dialog=TextDialog()
        dialog.original.setPlainText('Hello')
        dialog.work=lambda fn,done:done(fn())
        with patch('app.translate',return_value='你好') as translation:
            dialog.go.click()
        self.assertEqual(dialog.output.toPlainText(),'你好')
        translation.assert_called_once_with('Hello','auto','zh-CN')
        dialog.close()

    def test_capture_copy_never_writes_a_local_image(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from app import Home
        pix=QPixmap(100,60)
        pix.fill(QColor('#6059da'))
        controller=SimpleNamespace(clear_overlays=MagicMock())
        # An old enabled preference cannot restore the removed write path.
        with patch('app.flag',return_value=True),patch('app.save_new_png') as writer,patch.object(QPixmap,'save') as image_writer:
            Home.captured(controller,pix)
            writer.assert_not_called()
            image_writer.assert_not_called()
        self.assertEqual(app.clipboard().pixmap().toImage(),pix.toImage())
        controller.clear_overlays.assert_called_once()
        self.assertFalse(hasattr(Home,'history'))

    def test_settings_theme_icons_layout_and_removed_history_option(self):
        from unittest.mock import MagicMock
        from settings_ui import SettingsWindow,NAV_ICONS
        from PySide6.QtWidgets import QCheckBox
        window=SettingsWindow(MagicMock())
        window.grab()
        self.assertEqual(window.nav.count(),8)
        self.assertTrue(all(not window.nav.item(n).icon().isNull() for n in range(8)))
        self.assertNotIn('翻译',[window.nav.item(n).text() for n in range(window.nav.count())])
        self.assertFalse(hasattr(window,'title'))
        self.assertEqual(window.stack.y(),16)
        self.assertGreaterEqual(window.footer.y()-window.stack.geometry().bottom()-1,20)
        self.assertNotIn('capture/history',window.bindings)
        self.assertFalse(any('历史' in checkbox.text() for checkbox in window.findChildren(QCheckBox)))
        for row in range(window.nav.count()):
            window.nav.setCurrentRow(row)
            self.assertEqual(window.stack.currentIndex(),row)
        window.close()

    def test_ocr_dialog_recognizes_edits_and_copies_without_translation(self):
        from PySide6.QtWidgets import QPushButton, QComboBox
        pix=QPixmap(500,900)
        pix.fill(QColor('white'))
        with patch('app.recognize',return_value='Hello ABC\n中文识别 123') as recognize_mock,patch('app.translate') as translate_mock:
            dialog=OcrDialog(pix)
            dialog.show()
            for _ in range(100):
                QTest.qWait(10)
                if not dialog.text.isReadOnly():break
            self.assertEqual(dialog.text.toPlainText(),'Hello ABC\n中文识别 123')
            recognize_mock.assert_called_once_with(png_bytes(pix),layout=True)
            translate_mock.assert_not_called()
            self.assertEqual(dialog.preview.source.toImage(),pix.toImage())
            self.assertEqual(dialog.split.count(),2)
            self.assertTrue(dialog.preview.verticalScrollBar().maximum()>0)
            self.assertEqual([b.text() for b in dialog.findChildren(QPushButton)],['复制','关闭'])
            self.assertTrue(dialog.copy_button.icon().isNull())
            self.assertFalse(dialog.findChildren(QComboBox))
            dialog.text.setPlainText('Edited text\n修改后的文字 ABC xyz')
            dialog.copy_button.click()
            self.assertEqual(app.clipboard().text(),'Edited text\n修改后的文字 ABC xyz')
            dialog.text.clear()
            self.assertFalse(dialog.copy_button.isEnabled())
            dialog.close_button.click()
            self.assertFalse(dialog.isVisible())

    def test_ocr_empty_or_error_allows_manual_correction(self):
        pix=QPixmap(100,100)
        pix.fill(QColor('white'))
        with patch.object(OcrDialog,'start_recognition'):
            dialog=OcrDialog(pix)
            QTest.qWait(1)
            dialog.recognized('')
            self.assertFalse(dialog.text.isReadOnly())
            self.assertFalse(dialog.copy_button.isEnabled())
            self.assertIn('未识别到文字',dialog.status.text())
            dialog.failed('model unavailable')
            self.assertIn('model unavailable',dialog.status.text())
            dialog.text.setPlainText('manual')
            self.assertTrue(dialog.copy_button.isEnabled())
            dialog.close()

    def test_image_ocr_entry_points_open_ocr_dialog(self):
        from unittest.mock import MagicMock
        from PySide6.QtCore import QRect
        from scroll_capture import ScrollCapture,image_array
        pix=QPixmap(300,120)
        pix.fill(QColor('white'))
        controller=MagicMock()
        controller.dialogs=[]
        screen=app.primaryScreen()
        frozen=QPixmap(screen.geometry().size())
        frozen.fill(QColor('white'))
        with patch('app.OcrDialog') as factory:
            pin=Pin(pix,controller)
            pin.open_text()
            self.assertEqual(factory.call_args.args[0].toImage(),pix.toImage())
            editor=Editor(pix,controller)
            editor.text()
            self.assertEqual(factory.call_args.args[0].toImage(),pix.toImage())
            overlay=Overlay(screen,frozen,controller)
            overlay.set_selection(QRect(80,80,300,120))
            expected=overlay.canvas.pixmap().toImage()
            overlay.ocr()
            self.assertEqual(factory.call_args.args[0].toImage(),expected)
            controller.clear_overlays.assert_called_once()
            scrolling=ScrollCapture(controller,screen,QRect(80,80,300,120),frozen)
            scrolling.parts=[image_array(pix)]
            scrolling.complete('ocr')
            self.assertEqual(factory.call_args.args[0].toImage(),pix.toImage())
            self.assertEqual(factory.call_count,4)
            self.assertEqual(factory.return_value.show.call_count,4)

    def test_quota_is_error(self):
        def opener(*args, **kwargs):
            return io.BytesIO(json.dumps({'responseStatus':403,'responseDetails':'quota'}).encode())
        with self.assertRaisesRegex(RuntimeError,'quota'):
            translate('Hello',opener=opener)

    def test_translate_chunked_response(self):
        calls=[]
        def opener(req, **kwargs):
            calls.append(req.full_url)
            return io.BytesIO(json.dumps({'responseStatus':200,'responseData':{'translatedText':'你好 &amp; 世界'}}).encode())
        self.assertEqual(translate('hello',opener=opener),'你好 & 世界')
        self.assertIn('langpair=en%7Czh-CN', calls[0])
        self.assertNotIn('key=',calls[0])

    def test_default_translation_uses_original_online_service(self):
        response=io.BytesIO(json.dumps({'responseStatus':200,'responseData':{'translatedText':'原服务译文'}}).encode())
        with patch('services.urllib.request.urlopen',return_value=response) as network:
            self.assertEqual(translate('Hello'),'原服务译文')
        network.assert_called_once()
        self.assertTrue(network.call_args.args[0].full_url.startswith('https://api.mymemory.translated.net/get?'))

    def test_annotation_undo_redo(self):
        pix=QPixmap(400,200)
        pix.fill(QColor('white'))
        c=Canvas(pix)
        original=png_bytes(c.pixmap())
        c.snapshot()
        c.start,c.end=QPoint(20,20),QPoint(150,100)
        c.mode='矩形'
        p=QPainter(c.image)
        c.draw(p)
        p.end()
        edited=png_bytes(c.pixmap())
        self.assertNotEqual(original,edited)
        c.undo()
        self.assertEqual(original,png_bytes(c.pixmap()))
        c.redo()
        self.assertEqual(edited,png_bytes(c.pixmap()))

    def test_local_ocr(self):
        pix=QPixmap(650,140)
        pix.fill(QColor('white'))
        p=QPainter(pix)
        p.setPen(QColor('black'))
        p.setFont(QFont('Arial',32))
        p.drawText(20,85,'Hello LightSnip 2026')
        p.end()
        result=recognize(png_bytes(pix))
        self.assertIn('2026',result)
        self.assertIn('Hello',result)
        print('OCR:',result)

    def test_wide_multiline_italic_english_ocr(self):
        pix=QPixmap(1100,65)
        pix.fill(QColor('#fafafa'))
        painter=QPainter(pix)
        painter.setPen(QColor('#202020'))
        font=QFont('Georgia',12)
        font.setItalic(True)
        painter.setFont(font)
        painter.drawText(12,23,'I plan to help you execute and build out my ideas.')
        painter.drawText(12,51,'Your help can turn my ideas into reality.')
        painter.end()
        text=recognize(png_bytes(pix))
        self.assertIn('ideas',text)
        self.assertIn('reality',text)

    def test_hints_survive_selection(self):
        from PySide6.QtCore import QRect
        screen=app.primaryScreen()
        overlay=Overlay(screen,screen.grabWindow(0))
        overlay.set_selection(QRect(100,100,500,200))
        self.assertFalse(overlay.hints.isHidden())
        self.assertIn('滚动长截图',' '.join(w.text() for w in overlay.hints.findChildren(__import__('PySide6.QtWidgets',fromlist=['QLabel']).QLabel)))
        overlay.close()

    def test_selection_and_editor(self):
        screen=app.primaryScreen()
        pix=QPixmap(screen.geometry().size()*2)
        pix.fill(QColor('white'))
        overlay=Overlay(screen,pix)
        selected=[]
        overlay.selected.connect(selected.append)
        QTest.mousePress(overlay,Qt.MouseButton.LeftButton,pos=QPoint(20,20))
        QTest.mouseRelease(overlay,Qt.MouseButton.LeftButton,pos=QPoint(119,69))
        self.assertEqual(len(selected),0)
        self.assertIsNotNone(overlay.canvas)
        overlay.finish()
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0].width(),200)
        self.assertEqual(selected[0].height(),100)
        editor=Editor(selected[0],None)
        self.assertFalse(editor.canvas.pixmap().isNull())
        editor.close()
        overlay.close()

    def test_move_selection_recrops_desktop_without_finishing(self):
        from PySide6.QtCore import QRect, QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        screen=app.primaryScreen()
        frozen=QPixmap(screen.geometry().size()*2)
        frozen.fill(QColor('white'))
        painter=QPainter(frozen)
        painter.fillRect(QRect(200,200,100,100),QColor('red'))
        painter.fillRect(QRect(400,300,100,100),QColor('blue'))
        painter.end()
        overlay=Overlay(screen,frozen)
        selected=[]
        overlay.selected.connect(selected.append)
        overlay.set_selection(QRect(100,100,50,50))
        self.assertEqual(overlay.mode,'选区')
        self.assertTrue(overlay.canvas.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertEqual(overlay.canvas.image.pixelColor(50,50),QColor('red'))
        QTest.mousePress(overlay,Qt.MouseButton.LeftButton,pos=QPoint(125,125))
        def drag_to(pos):
            event=QMouseEvent(QEvent.Type.MouseMove,QPointF(pos),QPointF(overlay.mapToGlobal(pos)),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
            app.sendEvent(overlay,event)
        drag_to(QPoint(225,175))
        self.assertEqual(overlay.rect_selected,QRect(200,150,50,50))
        preview=overlay.grab().toImage()
        self.assertEqual(preview.pixelColor(220,170),QColor('blue'))
        self.assertNotEqual(preview.pixelColor(120,120),QColor('red'))
        QTest.mouseRelease(overlay,Qt.MouseButton.LeftButton,pos=QPoint(225,175))
        self.assertEqual(overlay.canvas.image.pixelColor(50,50),QColor('blue'))
        self.assertEqual(overlay.canvas.pos(),QPoint(200,150))
        self.assertEqual(overlay.canvas.pixmap().size(),frozen.copy(400,300,100,100).size())
        self.assertEqual(selected,[])
        # The selection keeps its size and stays within the screen at the edge.
        QTest.mousePress(overlay,Qt.MouseButton.LeftButton,pos=QPoint(225,175))
        drag_to(QPoint(-100,-100))
        QTest.mouseRelease(overlay,Qt.MouseButton.LeftButton,pos=QPoint(-100,-100))
        self.assertEqual(overlay.rect_selected,QRect(0,0,50,50))
        self.assertEqual(overlay.canvas.image.pixelColor(50,50),QColor('white'))
        self.assertEqual(selected,[])
        overlay.close()

    def test_ctrl_c_copies_image_and_closes_all_capture_windows(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from PySide6.QtCore import QRect,QTimer
        from app import Home
        screen=app.primaryScreen()
        frozen=QPixmap(screen.geometry().size())
        frozen.fill(QColor('#74b1df'))
        for focus in ['selection','toolbar','text']:
            with self.subTest(focus=focus),patch('app.flag',return_value=False):
                controller=SimpleNamespace(overlays=[],capture_screen_timer=QTimer(),tray=MagicMock())
                controller.clear_overlays=lambda:Home.clear_overlays(controller)
                overlay=Overlay(screen,frozen)
                other=Overlay(screen,frozen)
                controller.overlays=[overlay,other]
                overlay.selected.connect(lambda pix:Home.captured(controller,pix))
                overlay.set_selection(QRect(80,80,400,240))
                other.show()
                overlay.show()
                overlay.activateWindow()
                target=overlay
                if focus=='toolbar':target=overlay.actions['矩形']
                elif focus=='text':
                    overlay.tool('文字')
                    overlay.canvas.begin_text(QPoint(30,30))
                    overlay.canvas.text_editor.setPlainText('Current annotation')
                    target=overlay.canvas.text_editor
                target.setFocus()
                QTest.keyClick(target,Qt.Key.Key_C,Qt.KeyboardModifier.ControlModifier)
                self.assertEqual(controller.overlays,[])
                self.assertFalse(overlay.isVisible())
                self.assertFalse(other.isVisible())
                copied=app.clipboard().pixmap()
                self.assertEqual(copied.size(),QRect(0,0,400,240).size())
                if focus=='text':
                    self.assertIsNone(overlay.canvas.text_editor)
                    self.assertNotEqual(copied.toImage(),frozen.copy(80,80,400,240).toImage())
                else:self.assertEqual(copied.toImage(),frozen.copy(80,80,400,240).toImage())

    def test_settings_autostart_and_developer_information(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QLabel
        from settings_ui import SettingsWindow
        controller=MagicMock()
        controller.hotkeys.rebind.return_value=(True,'')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            cfg=QSettings(str(Path(folder)/'settings.ini'),QSettings.Format.IniFormat)
            with patch('settings_ui.preferences',return_value=cfg),patch('settings_ui.startup.is_enabled',return_value=True),patch('settings_ui.startup.set_enabled') as setter:
                window=SettingsWindow(controller)
                self.assertTrue(window.autostart.isChecked())
                window.autostart.setChecked(False)
                window.apply()
                setter.assert_called_once_with(False)
                self.assertFalse(cfg.value('system/autostart',True,type=bool))
                window.autostart.setChecked(True)
                window.apply()
                self.assertTrue(cfg.value('system/autostart',False,type=bool))
                setter.side_effect=PermissionError('denied')
                window.autostart.setChecked(False)
                window.apply()
                self.assertIn('设置失败',window.message.text())
                self.assertTrue(cfg.value('system/autostart',False,type=bool))
                text=' '.join(label.text() for label in window.findChildren(QLabel))
                self.assertIn('开发者：ZiP1824',text)
                self.assertIn('zhangxh1994@gmail.com',text)
                window.close()

    def test_cross_screen_copy_and_hints_stay_with_selection(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from PySide6.QtCore import QRect,QTimer
        from app import Home
        geometries=[QRect(0,0,900,600),QRect(900,0,900,600)]
        for source_index in [0,1]:
            with self.subTest(source_screen=source_index),patch('app.flag',side_effect=lambda name,default=False:name=='capture/hints'):
                controller=SimpleNamespace(overlays=[],current_capture=None,capture_screen_timer=QTimer(),tray=MagicMock())
                controller.clear_overlays=lambda:Home.clear_overlays(controller)
                for index,geometry in enumerate(geometries):
                    screen=SimpleNamespace(geometry=lambda rect=geometry:rect)
                    frozen=QPixmap(geometry.size()*2)
                    frozen.fill(QColor('#3290cf' if index==0 else '#c96c44'))
                    overlay=Overlay(screen,frozen,controller)
                    overlay.selected.connect(lambda pix:Home.captured(controller,pix))
                    controller.overlays.append(overlay)
                    overlay.show()
                source=controller.overlays[source_index]
                other=controller.overlays[1-source_index]
                source.set_selection(QRect(80,80,320,180))
                source.tool('文字')
                source.canvas.begin_text(QPoint(30,30))
                source.canvas.text_editor.setPlainText('Cross screen annotation')
                # Mouse focus moves to the screen with no selected pixels.
                Home.sync_capture_screen(controller,other.geometry().center())
                self.assertFalse(source.active_screen)
                self.assertTrue(other.active_screen)
                # Tight screens can now hide the hints when every safe corner
                # is occupied by the selection or annotation toolbar.
                if not source.hints.isHidden():
                    self.assertFalse(source.hints.geometry().intersects(source.rect_selected))
                self.assertTrue(other.hints.isHidden())
                self.assertIs(other.copy_source(),source)
                other.setFocus()
                QTest.keyClick(other,Qt.Key.Key_C,Qt.KeyboardModifier.ControlModifier)
                copied=app.clipboard().pixmap()
                self.assertEqual(copied.size(),QRect(0,0,640,360).size())
                self.assertEqual(copied.toImage().pixelColor(0,0),QColor('#3290cf' if source_index==0 else '#c96c44'))
                self.assertIsNone(source.canvas.text_editor)
                self.assertFalse(source.isVisible())
                self.assertFalse(other.isVisible())
                self.assertEqual(controller.overlays,[])
                self.assertIsNone(controller.current_capture)

    def test_arrow_default_width_is_separate_and_remembers_session_changes(self):
        import tempfile
        from pathlib import Path
        from PySide6.QtCore import QSettings,QRect
        from settings_ui import SettingsWindow
        from unittest.mock import MagicMock
        screen=app.primaryScreen()
        pix=QPixmap(screen.geometry().size())
        pix.fill(QColor('white'))
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            cfg=QSettings(str(Path(folder)/'settings.ini'),QSettings.Format.IniFormat)
            # Existing line settings must not override the new arrow default.
            cfg.setValue('annotation/width',5)
            with patch('settings_ui.preferences',return_value=cfg),patch('app.preferences',return_value=cfg),patch('settings_ui.startup.is_enabled',return_value=False):
                overlay=Overlay(screen,pix)
                overlay.set_selection(QRect(80,80,400,220))
                overlay.tool('箭头')
                self.assertEqual(overlay.canvas.pen_width,8)
                self.assertEqual(overlay.options.width_widget.control.value(),8)
                overlay.options.set_width(12)
                overlay.tool('矩形')
                self.assertEqual(overlay.canvas.pen_width,5)
                overlay.options.set_width(6)
                overlay.tool('箭头')
                self.assertEqual(overlay.canvas.pen_width,12)
                self.assertEqual(overlay.options.width_widget.number.text(),'12')
                overlay.tool('画笔')
                self.assertEqual(overlay.canvas.pen_width,6)
                settings=SettingsWindow(MagicMock())
                self.assertEqual(settings.bindings['annotation/arrow_width'][0].value(),8)
                self.assertEqual(settings.bindings['annotation/width'][0].value(),5)
                settings.close()
                cfg.setValue('annotation/arrow_width',10)
                editor=Editor(pix,None)
                self.assertEqual(editor.canvas.pen_width,10)
                self.assertEqual(editor.options.width_widget.control.value(),10)

    def test_hotkeys_validate_and_rollback(self):
        from app import Hotkeys
        self.assertEqual(Hotkeys.decode('Ctrl+Shift+1'),(0x4006,0x31))
        with patch('app.keys',return_value={}):
            hotkeys=Hotkeys(None)
        hotkeys.current={1:'Ctrl+Shift+1'}
        ok,msg=hotkeys.rebind({1:'Ctrl+A',2:'Ctrl+A'})
        self.assertFalse(ok)
        self.assertIn('重复',msg)
        with patch.object(hotkeys,'cleanup'),patch.object(hotkeys,'register',side_effect=[False,True]) as register:
            ok,msg=hotkeys.rebind({1:'Ctrl+Alt+2'})
            self.assertFalse(ok)
            self.assertEqual(register.call_args_list[-1].args,(1,'Ctrl+Shift+1'))

    def test_native_capture_copy_does_not_depend_on_widget_focus(self):
        import ctypes
        from ctypes.wintypes import MSG
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from app import Hotkeys
        controller=SimpleNamespace(copy_capture=MagicMock())
        with patch('app.keys',return_value={}):hotkeys=Hotkeys(controller)
        with patch('app.ctypes.windll.user32.RegisterHotKey',return_value=1) as register,patch('app.ctypes.windll.user32.UnregisterHotKey') as unregister:
            self.assertTrue(hotkeys.start_capture_copy(''))
            self.assertTrue(hotkeys.start_capture_copy(''))
            register.assert_called_once_with(None,100,0x4002,0x43)
            message=MSG()
            message.message=0x0312
            message.wParam=100
            self.assertEqual(hotkeys.nativeEventFilter(None,ctypes.addressof(message)),(True,0))
            QTest.qWait(1)
            controller.copy_capture.assert_called_once()
            hotkeys.stop_capture_copy()
            unregister.assert_called_once_with(None,100)
            self.assertNotIn(100,hotkeys.registered)

    def test_scroll_capture_uses_fixed_content_compositor(self):
        import time
        from test_scroll_stitcher import ScrollChecks
        from scroll_capture import ScrollCapture,image_array
        from PySide6.QtCore import QRect
        data=ScrollChecks()
        data.setUp()
        screen=app.primaryScreen()
        capture=ScrollCapture(None,screen,QRect(80,80,400,500),screen.grabWindow(0))
        capture.previous=data.frame(0,True)
        capture.parts=[capture.previous]
        capture.total=500
        capture.started=True
        for offset in [100,200,300]:
            capture.last_wheel=time.monotonic()
            with patch.object(capture,'grab',return_value=data.frame(offset,True)):
                capture.tick()
        self.assertEqual(capture.total,800)
        self.assertLessEqual(data.button_count(capture.full_frame()),1)
        self.assertEqual(int(__import__('numpy').all(capture.full_frame()==[200,50,30],axis=(1,2)).sum()),50)
        capture.cancel()

    def test_scrolling_overlap_and_unrelated_frame(self):
        import numpy as np
        from capture_tools import stitch_shift
        rng=np.random.default_rng(42)
        content=rng.integers(0,256,(1200,600,3),dtype=np.uint8)
        first=content[:600]
        next=content[140:740]
        self.assertEqual(stitch_shift(first,next),140)
        self.assertEqual(stitch_shift(first,first),0)
        self.assertIsNone(stitch_shift(first,content[600:1200]))

    def test_mp4_encoder_roundtrip(self):
        import cv2
        import numpy as np
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path=str(Path(folder)/'sample.mp4')
            writer=cv2.VideoWriter(path,cv2.VideoWriter_fourcc(*'mp4v'),10,(320,200))
            self.assertTrue(writer.isOpened())
            for _ in range(10):writer.write(np.zeros((200,320,3),dtype=np.uint8))
            writer.release()
            reader=cv2.VideoCapture(path)
            ok,frame=reader.read()
            count=reader.get(cv2.CAP_PROP_FRAME_COUNT)
            reader.release()
            self.assertTrue(ok)
            self.assertEqual(frame.shape[:2],(200,320))
            self.assertEqual(count,10)

    def test_scroll_region_wheel_gate(self):
        from scroll_capture import ScrollCapture
        from PySide6.QtCore import QRect
        screen=app.primaryScreen()
        capture=ScrollCapture(None,screen,QRect(80,80,400,250),screen.grabWindow(0))
        with patch.object(capture,'cursor_inside',return_value=False):capture.on_wheel()
        self.assertFalse(capture.started)
        with patch.object(capture,'cursor_inside',return_value=True):capture.on_wheel()
        self.assertTrue(capture.started)
        self.assertFalse(capture.mask().contains(QPoint(100,100)))
        capture.cancel()

    def test_translation_popup_auto_chain_and_copy(self):
        from translation_popup import TranslationPopup
        from PySide6.QtCore import QRect
        pix=QPixmap(300,80)
        pix.fill(QColor('white'))
        popup=TranslationPopup(pix,QRect(60,60,300,80))
        popup.work=lambda fn,done:done(fn())
        with patch('services.recognize',return_value='Hello'),patch('services.translate',return_value='你好') as translation:
            popup.start()
            self.assertEqual(popup.translation,'你好')
            self.assertTrue(translation.called)
            popup.copy.click()
            self.assertEqual(app.clipboard().text(),'你好')
        popup.close()
        with patch('services.translate') as translation:
            popup.recognized('Hidden popup')
            self.assertFalse(translation.called)

    def test_arrow_styles_and_controls(self):
        from annotation_tools import ARROWS,DASHES
        from PySide6.QtCore import QRect
        pix=QPixmap(300,100)
        pix.fill(QColor('white'))
        outputs=[]
        for style in ARROWS:
            c=Canvas(pix)
            c.start,c.end=QPoint(25,50),QPoint(265,50)
            c.arrow_style=style
            painter=QPainter(c.image)
            c.draw(painter)
            painter.end()
            outputs.append(png_bytes(c.pixmap()))
        self.assertEqual(len(set(outputs)),len(ARROWS))
        screen=app.primaryScreen()
        frozen=QPixmap(screen.geometry().size())
        frozen.fill(QColor('white'))
        overlay=Overlay(screen,frozen)
        overlay.set_selection(QRect(100,100,500,250))
        overlay.tool('箭头')
        overlay.options.choose_arrow('双向开放箭头')
        overlay.options.choose_dash('点划线')
        overlay.options.set_width(12)
        overlay.options.set_color(QColor('#26a979'))
        self.assertEqual(overlay.canvas.arrow_style,'双向开放箭头')
        self.assertEqual(overlay.canvas.line_style,DASHES['点划线'])
        self.assertEqual(overlay.canvas.pen_width,12)
        self.assertEqual(overlay.bar.cursor().shape(),Qt.CursorShape.ArrowCursor)
        self.assertEqual(overlay.canvas.cursor().shape(),Qt.CursorShape.ArrowCursor)
        overlay.tool('文字')
        self.assertEqual(overlay.canvas.cursor().shape(),Qt.CursorShape.ArrowCursor)
        overlay.tool('矩形')
        overlay.options.fill_changed(True)
        self.assertTrue(overlay.canvas.fill_shape)
        rendered=overlay.grab().toImage()
        color=rendered.pixelColor(101,200)
        self.assertGreater(color.blue(),220)
        self.assertLess(color.red(),100)
        overlay.close()

    def test_arrow_tip_resize_and_color_dialog(self):
        from PySide6.QtCore import QRect
        pix=QPixmap(300,100)
        pix.fill(QColor('white'))
        c=Canvas(pix)
        self.assertEqual(c.arrow_style,'渐细箭头')
        c.start,c.end=QPoint(30,50),QPoint(250,50)
        c.arrow_style='实心箭头'
        c.pen_width=18
        painter=QPainter(c.image)
        c.draw(painter)
        painter.end()
        self.assertEqual(c.image.pixelColor(255,50),QColor('white'))
        screen=app.primaryScreen()
        frozen=QPixmap(screen.geometry().size())
        frozen.fill(QColor('white'))
        o=Overlay(screen,frozen)
        o.set_selection(QRect(100,100,500,250))
        o.tool('箭头')
        self.assertEqual(o.canvas.arrow_style,'渐细箭头')
        # Resize from within the image edge while a drawing tool is selected.
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent,QPointF
        hover=QMouseEvent(QEvent.Type.MouseMove,QPointF(498,100),QPointF(598,200),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
        app.sendEvent(o.canvas,hover)
        self.assertEqual(o.canvas.cursor().shape(),Qt.CursorShape.SizeHorCursor)
        QTest.mousePress(o.canvas,Qt.MouseButton.LeftButton,pos=QPoint(498,100))
        move=QMouseEvent(QEvent.Type.MouseMove,QPointF(680,200),QPointF(680,200),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        o.mouseMoveEvent(move)
        self.assertTrue(o.canvas.isHidden())
        rendered=o.grab().toImage()
        self.assertEqual(rendered.pixelColor(400,220),QColor('white'))
        QTest.mouseRelease(o,Qt.MouseButton.LeftButton,pos=QPoint(680,200))
        self.assertEqual(o.rect_selected.width(),582)
        self.assertEqual(o.mode,'箭头')
        o.update_pointer(o.canvas.pos()+QPoint(100,100))
        o.canvas.update_badge(QPoint(100,100))
        self.assertFalse(o.canvas.cursor_badge.isHidden())
        o.options.custom_color()
        self.assertTrue(o.options.color_dialog.isVisible())
        o.options.color_dialog.setCurrentColor(QColor('#102030'))
        o.options.color_dialog.accept()
        self.assertEqual(o.canvas.color.name(),'#102030')
        o.close()

    def test_resize_cursor_only_on_blue_line(self):
        from PySide6.QtCore import QRect,QEvent,QPointF
        from PySide6.QtGui import QMouseEvent
        from annotation_tools import BORDER_WIDTH
        self.assertEqual(BORDER_WIDTH,4)
        screen=app.primaryScreen()
        frozen=QPixmap(screen.geometry().size())
        frozen.fill(QColor('white'))
        o=Overlay(screen,frozen)
        o.set_selection(QRect(100,100,500,250))
        o.tool('箭头')
        def hover(local):
            event=QMouseEvent(QEvent.Type.MouseMove,QPointF(local),QPointF(local+o.canvas.pos()),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
            app.sendEvent(o.canvas,event)
        hover(QPoint(250,249))
        self.assertEqual(o.canvas.cursor().shape(),Qt.CursorShape.SizeVerCursor)
        hover(QPoint(250,240))
        self.assertEqual(o.canvas.cursor().shape(),Qt.CursorShape.ArrowCursor)
        self.assertFalse(o.canvas.property('edge_hover'))
        self.assertIsNone(o.edge_at(QPoint(350,355)))
        o.update_pointer(QPoint(350,349))
        self.assertEqual(o.cursor().shape(),Qt.CursorShape.SizeVerCursor)
        o.update_pointer(QPoint(350,360))
        self.assertEqual(o.cursor().shape(),Qt.CursorShape.ArrowCursor)
        # A missing mouse-release event must not leave the resize cursor latched.
        o.drag_kind=5
        hover(QPoint(250,200))
        self.assertIsNone(o.drag_kind)
        self.assertEqual(o.canvas.cursor().shape(),Qt.CursorShape.ArrowCursor)
        rendered=o.grab().toImage()
        self.assertGreater(rendered.pixelColor(101,210).blue(),220)
        self.assertLess(rendered.pixelColor(101,210).red(),100)
        o.close()

    def test_translucent_fill_has_no_inner_stroke(self):
        for mode in ['矩形','圆角矩形','椭圆']:
            pix=QPixmap(260,180)
            pix.fill(QColor('white'))
            c=Canvas(pix)
            c.mode=mode
            c.fill_shape=True
            c.pen_width=18
            c.color=QColor(255,0,0,90)
            c.start,c.end=QPoint(25,25),QPoint(230,150)
            painter=QPainter(c.image)
            c.draw(painter)
            painter.end()
            center=c.image.pixelColor(125,85)
            near_edge=c.image.pixelColor(30,85)
            self.assertEqual(center,near_edge,mode)

    def test_multi_screen_preparation_hints(self):
        screen=app.primaryScreen()
        frozen=QPixmap(screen.geometry().size())
        frozen.fill(QColor('white'))
        left,right=Overlay(screen,frozen),Overlay(screen,frozen)
        point=QPoint(20,20)
        left.set_capture_active(False,point)
        right.set_capture_active(True,point)
        self.assertTrue(left.hints.isHidden())
        self.assertFalse(right.hints.isHidden())
        left.set_capture_active(True,point)
        right.set_capture_active(False,point)
        self.assertFalse(left.hints.isHidden())
        self.assertTrue(right.hints.isHidden())
        self.assertFalse(right.active_screen)
        left.close()
        right.close()

    def test_inline_multiline_text_and_formatting(self):
        pix=QPixmap(700,300)
        pix.fill(QColor('white'))
        c=Canvas(pix)
        c.mode='文字'
        c.begin_text(QPoint(30,30))
        self.assertIsNotNone(c.text_editor)
        c.text_editor.setPlainText('Hello LightSnip\n原位输入文字')
        c.text_bold=True
        c.text_italic=True
        c.font_size=28
        c.update_text_editor_style()
        self.assertTrue(c.text_editor.font().bold())
        self.assertTrue(c.text_editor.font().italic())
        before=pix.toImage()
        c.commit_text()
        self.assertIsNone(c.text_editor)
        self.assertNotEqual(c.pixmap().toImage(),before)
        c.undo()
        self.assertEqual(c.pixmap().toImage(),before)
        c.begin_text(QPoint(30,30))
        c.text_editor.setPlainText('取消输入')
        QTest.keyClick(c.text_editor,Qt.Key.Key_Escape)
        self.assertIsNone(c.text_editor)

    def test_text_wrap_move_resize_and_reformat_after_commit(self):
        pix=QPixmap(480,320)
        pix.fill(QColor('white'))
        c=Canvas(pix)
        c.mode='文字'
        c.show()
        c.begin_text(QPoint(90,280))
        editor=c.text_editor
        self.assertLess(editor.width(),70)
        editor.insertPlainText('长')
        app.processEvents()
        one_character_width=editor.width()
        editor.insertPlainText('文字')
        app.processEvents()
        self.assertGreater(editor.width(),one_character_width)
        text='长文字需要在截图的右边界自动换行。'*3+'\n手动换行'
        editor.setPlainText(text.split('\n')[0])
        editor.moveCursor(editor.textCursor().MoveOperation.End)
        QTest.keyClick(editor,Qt.Key.Key_Return)
        editor.insertPlainText('手动换行')
        app.processEvents()
        self.assertEqual(editor.toPlainText(),text)
        self.assertEqual(editor.width(),390)
        self.assertTrue(c.rect().contains(editor.geometry()))
        self.assertGreaterEqual(editor.viewport().height(),int(editor.document().size().height()))
        self.assertEqual(editor.verticalScrollBarPolicy(),Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertEqual(editor.horizontalScrollBarPolicy(),Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        c.commit_text()
        mark=c.text_marks[0]
        self.assertEqual(mark.text,text)
        # A separate short label leaves room to test moving and enlarging.
        c.begin_text(QPoint(40,30))
        c.text_editor.setPlainText('Editable')
        c.commit_text()
        mark=c.text_marks[1]
        point=mark.rect().center()
        QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=point)
        QTest.mouseMove(c,point+QPoint(35,20))
        QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=point+QPoint(35,20))
        self.assertEqual(c.text_marks[1].position,mark.position+QPoint(35,20))
        handle=c.text_handle().center()
        QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=handle)
        QTest.mouseMove(c,handle+QPoint(40,30))
        QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=handle+QPoint(40,30))
        self.assertGreater(c.text_marks[1].scale,1)
        QTest.keyClick(c,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(c.text_editor.textCursor().selectedText(),'Editable')
        c.color=QColor('#2244bb')
        c.text_bold=True
        c.update_text_editor_style()
        c.commit_text()
        document=c.text_marks[1].create_document()
        cursor=document.find('Editable')
        self.assertTrue(cursor.charFormat().font().bold())
        self.assertEqual(cursor.charFormat().foreground().color(),QColor('#2244bb'))
        self.assertTrue(c.rect().contains(c.text_marks[1].rect()))
        c.undo()
        self.assertGreater(c.text_marks[1].scale,1)
        c.redo()
        self.assertEqual(c.text_marks[1].style[4],QColor('#2244bb'))
        c.close()

    def test_text_border_drag_and_visibility_after_switching_tools(self):
        from app import Editor, LIGHT_STYLE
        from PySide6.QtCore import QEvent, QPointF, QRect
        from PySide6.QtGui import QMouseEvent
        pix=QPixmap(520,280)
        pix.fill(QColor('white'))
        editor=Editor(pix,None)
        editor.setStyleSheet(LIGHT_STYLE)
        editor.show()
        editor.tool('文字')
        canvas=editor.canvas
        canvas.begin_text(QPoint(60,50))
        field=canvas.text_editor
        field.setPlainText('移动后保留文字')
        app.processEvents()
        edge=QPoint(field.width()//2,0)
        def move_field_pointer(point,buttons=Qt.MouseButton.NoButton):
            event=QMouseEvent(QEvent.Type.MouseMove,QPointF(point),QPointF(field.mapToGlobal(point)),
                              Qt.MouseButton.NoButton,buttons,Qt.KeyboardModifier.NoModifier)
            app.sendEvent(field,event)
        move_field_pointer(edge)
        self.assertEqual(field.cursor().shape(),Qt.CursorShape.SizeAllCursor)
        start=field.pos()
        QTest.mousePress(field,Qt.MouseButton.LeftButton,pos=edge)
        move_field_pointer(edge+QPoint(45,30),Qt.MouseButton.LeftButton)
        QTest.mouseRelease(field,Qt.MouseButton.LeftButton,pos=edge)
        self.assertEqual(field.pos(),start+QPoint(45,30))
        self.assertEqual(field.toPlainText(),'移动后保留文字')
        QTest.keyClick(field,Qt.Key.Key_Return,Qt.KeyboardModifier.ControlModifier)
        mark=canvas.text_marks[0]
        point=mark.rect().center()
        QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=point)
        self.assertEqual(canvas.selected_text,0)
        self.assertIsNone(canvas.text_editor)
        editor.tool('箭头')
        app.processEvents()
        exported=canvas.pixmap().toImage()
        rendered=editor.grab()
        ratio=rendered.devicePixelRatio()
        visible=rendered.copy(QRect(canvas.mapTo(editor,QPoint())*ratio,canvas.size()*ratio)).toImage()
        if visible.size()!=exported.size():visible=visible.scaled(exported.size())
        self.assertNotEqual(exported,pix.toImage())
        def red_pixels(image):
            return sum(1 for x in range(mark.rect().left(),mark.rect().right())
                       for y in range(mark.rect().top(),mark.rect().bottom())
                       if (color:=image.pixelColor(x,y)).red()>180 and color.green()<140)
        self.assertGreater(red_pixels(exported),30)
        self.assertGreater(red_pixels(visible),30)
        editor.tool('文字')
        QTest.mouseDClick(canvas,Qt.MouseButton.LeftButton,pos=point)
        self.assertEqual(canvas.text_editor.toPlainText(),'移动后保留文字')
        canvas.text_editor.clear()
        editor.tool('箭头')
        self.assertEqual(canvas.text_marks[0].text,'移动后保留文字')
        editor.close()

    def test_overlay_click_and_selection_move_preserve_text(self):
        from PySide6.QtCore import QRect
        screen=app.primaryScreen()
        pix=QPixmap(screen.geometry().size())
        pix.fill(QColor('white'))
        with patch('app.flag',return_value=False):
            overlay=Overlay(screen,pix)
            overlay.set_selection(QRect(50,50,460,240))
            overlay.show()
            overlay.tool('文字')
            canvas=overlay.canvas
            canvas.begin_text(QPoint(80,60))
            canvas.text_editor.setPlainText('文字不会因选区点击消失')
            overlay.tool('选区')
            point=canvas.pos()+canvas.text_marks[0].rect().center()
            QTest.mouseClick(overlay,Qt.MouseButton.LeftButton,pos=point)
            self.assertIs(overlay.canvas,canvas)
            self.assertEqual(len(canvas.text_marks),1)
            QTest.mousePress(overlay,Qt.MouseButton.LeftButton,pos=point)
            QTest.mouseMove(overlay,point+QPoint(25,20))
            QTest.mouseRelease(overlay,Qt.MouseButton.LeftButton,pos=point+QPoint(25,20))
            self.assertEqual(overlay.rect_selected.topLeft(),QPoint(75,70))
            self.assertEqual(overlay.canvas.text_marks[0].text,'文字不会因选区点击消失')
            self.assertNotEqual(overlay.canvas.pixmap().toImage(),overlay.canvas.image)
            overlay.close()

    def test_inline_ime_preedit_fits_on_the_current_line(self):
        from PySide6.QtGui import QInputMethodEvent
        pix=QPixmap(400,180)
        pix.fill(QColor('white'))
        canvas=Canvas(pix)
        canvas.mode='文字'
        canvas.show()
        canvas.begin_text(QPoint(30,40))
        editor=canvas.text_editor
        editor.insertPlainText('已经确认的中文')
        app.processEvents()
        width=editor.width()
        height=editor.height()
        app.sendEvent(editor,QInputMethodEvent('zhongwen',[]))
        app.processEvents()
        self.assertTrue(editor.composing)
        self.assertGreater(editor.width(),width)
        self.assertEqual(editor.height(),height)
        self.assertEqual(editor.document().firstBlock().layout().lineCount(),1)
        self.assertEqual(editor.toPlainText(),'已经确认的中文')
        event=QInputMethodEvent('',[])
        event.setCommitString('中文输入')
        app.sendEvent(editor,event)
        app.processEvents()
        self.assertFalse(editor.composing)
        self.assertGreater(editor.width(),width)
        canvas.commit_text()
        self.assertEqual(canvas.text_marks[0].text,'已经确认的中文中文输入')
        self.assertNotEqual(canvas.pixmap().toImage(),canvas.image)
        canvas.close()

    def test_double_click_text_in_selection_mode_reopens_it_without_finishing(self):
        from PySide6.QtCore import QRect
        screen=app.primaryScreen()
        pix=QPixmap(screen.geometry().size())
        pix.fill(QColor('white'))
        with patch('app.flag',return_value=False):
            overlay=Overlay(screen,pix)
            overlay.set_selection(QRect(60,60,420,220))
            overlay.show()
            overlay.tool('文字')
            canvas=overlay.canvas
            canvas.begin_text(QPoint(36,42))
            canvas.text_editor.setPlainText('二次编辑测试')
            overlay.tool('选区')
            output=[]
            overlay.selected.connect(output.append)
            point=canvas.pos()+canvas.text_marks[0].rect().center()
            QTest.mouseClick(overlay,Qt.MouseButton.LeftButton,pos=point)
            QTest.mouseDClick(overlay,Qt.MouseButton.LeftButton,pos=point)
            self.assertEqual(output,[])
            self.assertEqual(overlay.mode,'文字')
            self.assertEqual(canvas.text_editor.toPlainText(),'二次编辑测试')
            canvas.text_editor.selectAll()
            canvas.text_editor.insertPlainText('已重新编辑')
            QTest.keyClick(canvas.text_editor,Qt.Key.Key_Return,Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(len(canvas.text_marks),1)
            self.assertEqual(canvas.text_marks[0].text,'已重新编辑')
            overlay.close()

    def test_export_and_import_applied_settings(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from PySide6.QtCore import QSettings
        from PySide6.QtGui import QKeySequence
        from settings_ui import SettingsWindow
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=Path(folder)
            cfg=QSettings(str(root/'settings.ini'),QSettings.Format.IniFormat)
            cfg.setValue('capture/delay',7)
            cfg.setValue('keys/7','F9')
            cfg.setValue('save/path',str(root))
            controller=MagicMock()
            controller.hotkeys.rebind.return_value=(True,'')
            path=root/'backup.json'
            with patch('settings_ui.preferences',return_value=cfg), \
                    patch('settings_ui.startup.is_enabled',return_value=False), \
                    patch('settings_ui.startup.set_enabled'), \
                    patch('settings_ui.QFileDialog.getSaveFileName',return_value=(str(path),'')), \
                    patch('settings_ui.QFileDialog.getOpenFileName',return_value=(str(path),'')):
                window=SettingsWindow(controller)
                delay=window.bindings['capture/delay'][0]
                delay.setValue(12)
                window.export_config()
                exported=json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(exported['settings']['capture/delay'],7)
                self.assertEqual(exported['settings']['keys/7'],'F9')
                self.assertEqual(Path(exported['settings']['save/path']),root)
                cfg.setValue('capture/delay',3)
                window.key_edits[7].setKeySequence(QKeySequence('F10'))
                window.import_config()
                self.assertEqual(delay.value(),7)
                self.assertEqual(window.key_edits[7].keySequence().toString(),'F9')
                self.assertEqual(cfg.value('capture/delay',type=int),3)
                self.assertTrue(window.apply())
                self.assertEqual(cfg.value('capture/delay',type=int),7)
                exported['settings']['capture/delay']=99
                path.write_text(json.dumps(exported),encoding='utf-8')
                window.import_config()
                self.assertEqual(delay.value(),7)
                self.assertIn('导入失败',window.message.text())
                window.close()

    def test_selected_text_live_format_and_second_toolbar(self):
        from PySide6.QtCore import QRect,QEvent
        from PySide6.QtGui import QTextCursor,QFocusEvent
        from PySide6.QtWidgets import QToolButton
        screen=app.primaryScreen()
        pix=QPixmap(screen.geometry().size())
        pix.fill(QColor('white'))
        overlay=Overlay(screen,pix)
        overlay.set_selection(QRect(100,100,700,400))
        overlay.tool('文字')
        overlay.canvas.begin_text(QPoint(30,30))
        editor=overlay.canvas.text_editor
        editor.setPlainText('Live format test')
        editor.selectAll()
        app.sendEvent(editor,QFocusEvent(QEvent.Type.FocusOut))
        overlay.options.set_value('font_size',38)
        overlay.options.set_value('text_bold',True)
        overlay.options.set_color(QColor('#0022ee'))
        cursor=QTextCursor(editor.document())
        cursor.setPosition(2)
        format=cursor.charFormat()
        self.assertAlmostEqual(format.fontPointSize(),38)
        self.assertTrue(format.font().bold())
        self.assertEqual(format.foreground().color().name(),'#0022ee')
        overlay.tool('矩形')
        self.assertFalse(overlay.options.shape_choice.isHidden())
        overlay.options.shape_choice.setCurrentText('椭圆')
        self.assertEqual(overlay.canvas.mode,'椭圆')
        overlay.tool('画笔')
        overlay.options.pen_choice.setCurrentText('荧光笔')
        self.assertEqual(overlay.canvas.mode,'荧光笔')
        self.assertFalse(any(b.menu() for b in overlay.bar.findChildren(QToolButton) if b.toolTip() in ['矩形','圆角矩形','椭圆','画笔','荧光笔']))
        overlay.close()

    def test_unified_selectors_and_scroll_transition(self):
        from annotation_tools import PreviewSelector
        from scroll_capture import ScrollCapture
        from PySide6.QtCore import QRect
        screen=app.primaryScreen()
        frozen=QPixmap(screen.geometry().size())
        frozen.fill(QColor('white'))
        overlay=Overlay(screen,frozen)
        overlay.set_selection(QRect(100,100,500,300))
        choices=[overlay.options.shape_choice,overlay.options.pen_choice,overlay.options.arrow_button,overlay.options.dash_button]
        self.assertTrue(all(isinstance(w,PreviewSelector) for w in choices))
        self.assertEqual(len(set((w.width(),w.height()) for w in choices)),1)
        order=[]
        session=ScrollCapture(None,screen,overlay.rect_selected,frozen)
        session.start(initial_pixmap=overlay.crop(overlay.rect_selected),on_ready=lambda:order.append((session.isVisible(),session.transition_cover)))
        self.assertTrue(session.transition_cover)
        self.assertTrue(session.mask().contains(session.region.center()))
        from PySide6.QtCore import QElapsedTimer
        wait=QElapsedTimer()
        wait.start()
        while (not order or session.transition_cover) and wait.elapsed()<2000:
            QTest.qWait(20)
        self.assertEqual(order,[(True,True)])
        self.assertFalse(session.transition_cover)
        self.assertFalse(session.mask().contains(session.region.center()))
        self.assertTrue(session.timer.isActive())
        self.assertEqual(session.previous.shape[:2],(300,500))
        session.cancel()
        overlay.close()


if __name__=='__main__':
    unittest.main()
