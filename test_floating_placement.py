import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QRect,QPoint,QEvent,QCoreApplication,Qt
from PySide6.QtGui import QPixmap,QColor
from PySide6.QtWidgets import QApplication
from app import Overlay
from translation_popup import TranslationPopup

app=QApplication.instance() or QApplication([])


class FloatingPlacementChecks(unittest.TestCase):
    def tearDown(self):
        for widget in app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def overlay(self):
        screen=SimpleNamespace(geometry=lambda:QRect(0,0,1000,800))
        frozen=QPixmap(1000,800)
        frozen.fill(QColor('white'))
        return Overlay(screen,frozen)

    def test_hint_moves_away_from_corner_cursor_and_committed_selection(self):
        with patch('app.flag',return_value=True):
            overlay=self.overlay()
            old=overlay.hints.geometry()
            overlay.cursor_pos=old.center()
            overlay.position_hints()
            self.assertFalse(overlay.hints.geometry().contains(overlay.cursor_pos))
            selection=QRect(0,420,380,380)
            overlay.set_selection(selection)
            self.assertFalse(overlay.hints.isHidden())
            self.assertFalse(overlay.hints.geometry().intersects(selection))
            self.assertTrue(overlay.hints.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_hint_avoids_live_drag_and_hides_if_no_space_remains(self):
        with patch('app.flag',return_value=True):
            overlay=self.overlay()
            overlay.start=QPoint(0,400)
            overlay.end=QPoint(380,790)
            overlay.position_hints()
            self.assertFalse(overlay.hints.geometry().intersects(QRect(overlay.start,overlay.end)))
            overlay.start=overlay.end=None
            overlay.set_selection(overlay.rect())
            self.assertTrue(overlay.hints.isHidden())

    def popup(self,anchor):
        pix=QPixmap(300,80)
        pix.fill(QColor('white'))
        return TranslationPopup(pix,anchor)

    def test_translation_flips_above_bottom_edge_and_clamps_right_edge(self):
        popup=self.popup(QRect(850,720,150,70))
        popup.available=QRect(0,0,1000,800)
        popup.place()
        self.assertTrue(popup.available.contains(popup.geometry()))
        self.assertLess(popup.geometry().bottom(),popup.anchor.top())

    def test_long_translation_scrolls_inside_negative_coordinate_monitor(self):
        popup=self.popup(QRect(-80,700,60,90))
        popup.available=QRect(-1000,100,1000,700)
        popup.show()
        text='这是一段需要完整保留的翻译文字。Example translation.\n'*250
        popup.translated(text)
        app.processEvents()
        popup.place()
        app.processEvents()
        self.assertTrue(popup.available.contains(popup.geometry()))
        self.assertEqual(popup.translation,text)
        self.assertGreater(popup.scroll.verticalScrollBar().maximum(),0)
        popup.scroll.verticalScrollBar().setValue(popup.scroll.verticalScrollBar().maximum())
        self.assertTrue(popup.copy.isEnabled())
        popup.close()


if __name__=='__main__':unittest.main()
