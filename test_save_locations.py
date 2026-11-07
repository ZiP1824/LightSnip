import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from PySide6.QtCore import QSettings,QRect,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap,QColor,QImage
from app import Overlay,Editor,Pin
from scroll_capture import ScrollCapture,image_array
from file_names import remember_saved_file,save_directory,choose_save_path
from settings_ui import SettingsWindow

app=QApplication.instance() or QApplication([])


class SaveLocationChecks(unittest.TestCase):
    def tearDown(self):
        for widget in app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_all_image_save_windows_share_the_last_successful_folder(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=Path(folder)
            folders=[root/name for name in ['A','B','C']]
            for directory in folders:directory.mkdir()
            cfg=QSettings(str(root/'preferences.ini'),QSettings.Format.IniFormat)
            cfg.setValue('save/path',str(folders[0]))
            screen=app.primaryScreen()
            frozen=QPixmap(screen.geometry().size())
            frozen.fill(QColor('white'))
            pix=QPixmap(160,100)
            pix.fill(QColor('#6059da'))
            with patch('settings_ui.preferences',return_value=cfg),patch('app.QFileDialog.getSaveFileName') as dialog:
                overlay=Overlay(screen,frozen)
                overlay.set_selection(QRect(40,40,160,100))
                dialog.return_value=(str(folders[1]/'ordinary.png'),'')
                overlay.save()
                self.assertEqual(Path(dialog.call_args.args[2]).parent,folders[0])
                self.assertEqual(save_directory(),folders[1])
                pin=Pin(pix,None)
                dialog.return_value=(str(folders[2]/'pin.png'),'')
                pin.save()
                self.assertEqual(Path(dialog.call_args.args[2]).parent,folders[1])
                self.assertEqual(save_directory(),folders[2])
                editor=Editor(pix,None)
                dialog.return_value=('','')
                editor.save()
                self.assertEqual(Path(dialog.call_args.args[2]).parent,folders[2])
                self.assertEqual(save_directory(),folders[2])
                scroll=ScrollCapture(None,screen,QRect(40,40,160,100),frozen)
                scroll.parts=[image_array(pix)]
                dialog.return_value=(str(folders[1]/'long.png'),'')
                scroll.complete('save')
                self.assertEqual(Path(dialog.call_args.args[2]).parent,folders[2])
                self.assertEqual(save_directory(),folders[1])
                overlay.save(True)
                self.assertEqual(len(list(folders[1].glob('*.png'))),3)
                for path in folders[1].glob('*.png'):self.assertFalse(QImage(str(path)).isNull())
            # A fresh settings object (as after restart) reads the same folder.
            restarted=QSettings(str(root/'preferences.ini'),QSettings.Format.IniFormat)
            with patch('settings_ui.preferences',return_value=restarted):self.assertEqual(save_directory(),folders[1])

    def test_failed_save_and_cancel_do_not_change_remembered_folder(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=Path(folder)
            cfg=QSettings(str(root/'preferences.ini'),QSettings.Format.IniFormat)
            cfg.setValue('save/path',str(root))
            pix=QPixmap(80,50)
            pix.fill(QColor('white'))
            with patch('settings_ui.preferences',return_value=cfg),patch('app.QMessageBox.warning') as warning,patch('app.QFileDialog.getSaveFileName',return_value=(str(root/'missing'/'failed.png'),'')):
                editor=Editor(pix,None)
                editor.save()
                warning.assert_called_once()
                self.assertEqual(save_directory(),root)
            with patch('settings_ui.preferences',return_value=cfg),patch('app.QFileDialog.getSaveFileName',return_value=('','')):
                editor.save()
                self.assertEqual(save_directory(),root)

    def test_settings_refresh_remembered_folder_and_do_not_restore_stale_value(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=Path(folder)
            initial,last,configured=[root/name for name in ['initial','last','configured']]
            initial.mkdir()
            last.mkdir()
            cfg=QSettings(str(root/'preferences.ini'),QSettings.Format.IniFormat)
            cfg.setValue('save/path',str(initial))
            controller=MagicMock()
            controller.hotkeys.rebind.return_value=(True,'')
            with patch('settings_ui.preferences',return_value=cfg),patch('settings_ui.startup.is_enabled',return_value=False),patch('settings_ui.startup.set_enabled'):
                window=SettingsWindow(controller)
                self.assertEqual(Path(window.save_dir.text()),initial)
                remember_saved_file(last/'picture.png')
                window.apply()
                self.assertEqual(save_directory(),last)
                window.nav.setCurrentRow(3)
                self.assertEqual(Path(window.save_dir.text()),last)
                window.save_dir.setText(str(configured))
                window.apply()
                self.assertTrue(configured.is_dir())
                self.assertEqual(save_directory(),configured)
                with patch('app.QFileDialog.getSaveFileName',return_value=('','')) as dialog:
                    choose_save_path(window,'保存截图')
                    self.assertEqual(Path(dialog.call_args.args[2]).parent,configured)
                window.close()

    def test_successful_save_immediately_updates_open_and_dirty_settings(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=Path(folder)
            initial,pending,latest,another=[root/name for name in ['initial','pending','latest','another']]
            for directory in [initial,latest,another]:directory.mkdir()
            cfg=QSettings(str(root/'preferences.ini'),QSettings.Format.IniFormat)
            cfg.setValue('save/path',str(initial))
            controller=MagicMock()
            controller.hotkeys.rebind.return_value=(True,'')
            pix=QPixmap(80,50)
            pix.fill(QColor('#6059da'))
            with patch('settings_ui.preferences',return_value=cfg),patch('settings_ui.startup.is_enabled',return_value=False),patch('settings_ui.startup.set_enabled'):
                window=SettingsWindow(controller)
                window.nav.setCurrentRow(3)
                window.show()
                window.save_dir.setText(str(pending))
                self.assertTrue(window.save_dir.isModified())
                editor=Editor(pix,None)
                with patch('app.QFileDialog.getSaveFileName',return_value=(str(latest/'picture.png'),'')):
                    editor.save()
                # No reopening, tab change or Apply is needed for the update.
                self.assertEqual(Path(window.save_dir.text()),latest)
                self.assertFalse(window.save_dir.isModified())
                self.assertEqual(save_directory(),latest)
                window.apply()
                self.assertEqual(save_directory(),latest)
                self.assertFalse(pending.exists())
                pin=Pin(pix,None)
                with patch('app.QFileDialog.getSaveFileName',return_value=(str(another/'pin.png'),'')):
                    pin.save()
                self.assertEqual(Path(window.save_dir.text()),another)
                self.assertEqual(save_directory(),another)
                with patch('app.QFileDialog.getSaveFileName',return_value=('','')):
                    editor.save()
                self.assertEqual(Path(window.save_dir.text()),another)
                window.close()

    def test_quick_save_synchronizes_settings(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=Path(folder)
            target=root/'target'
            target.mkdir()
            cfg=QSettings(str(root/'preferences.ini'),QSettings.Format.IniFormat)
            cfg.setValue('save/path',str(target))
            screen=app.primaryScreen()
            frozen=QPixmap(screen.geometry().size())
            frozen.fill(QColor('white'))
            with patch('settings_ui.preferences',return_value=cfg),patch('settings_ui.startup.is_enabled',return_value=False):
                window=SettingsWindow(MagicMock())
                window.save_dir.setText(str(root/'stale'))
                overlay=Overlay(screen,frozen)
                overlay.set_selection(QRect(40,40,160,100))
                overlay.save(True)
                self.assertEqual(Path(window.save_dir.text()),target)
                self.assertFalse(window.save_dir.isModified())
                self.assertEqual(save_directory(),target)
                self.assertEqual(Path(window.save_dir.text()),target)
                window.close()


if __name__=='__main__':unittest.main()
