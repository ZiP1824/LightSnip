import unittest
from PySide6.QtCore import QPoint,QPointF,QRect,Qt,QEvent,QCoreApplication
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from element_detection import text_regions,ScanSignals
from window_detection import WindowCatalog,ScreenMapping
import test_window_detection as window_checks
app=window_checks.app


class RegionGeometryChecks(unittest.TestCase):
    def test_native_window_handles_are_preserved_without_32_bit_truncation(self):
        signals=ScanSignals()
        received=[]
        signals.ready.connect(lambda handle,regions:received.append(handle))
        signals.ready.emit((1<<48)+17,[])
        self.assertEqual(received,[(1<<48)+17])

    def test_line_fragments_and_wrapped_paragraphs_keep_columns_separate(self):
        regions=text_regions([QRect(20,20,100,20),QRect(128,20,110,20),QRect(20,50,230,20),
                              QRect(420,20,150,20),QRect(420,50,155,20),QRect(20,120,220,30)],QRect(0,0,800,400))
        lines=[r for kind,r in regions if kind=='line']
        paragraphs=[r for kind,r in regions if kind=='paragraph']
        self.assertEqual(len(lines),5)
        self.assertEqual(len(paragraphs),2)
        self.assertFalse(any(r.contains(QPoint(320,45)) for r in paragraphs))
        self.assertFalse(any(r.contains(QPoint(50,130)) for r in paragraphs))

    def test_nested_candidates_cover_line_paragraph_panel_and_window(self):
        mapping=ScreenMapping('screen',QRect(-1000,0,1000,700),QRect(-1500,0,1500,1050))
        catalog=WindowCatalog([mapping],[(1,QRect(-1450,0,1400,1000))])
        catalog.add_regions(1,[('line',QRect(-1300,100,300,30)),('paragraph',QRect(-1310,90,350,120)),('pane',QRect(-1400,50,1200,800))])
        targets=catalog.candidates_at(QPoint(-800,75))
        self.assertEqual([t.kind for t in targets],['line','paragraph','pane','window'])
        self.assertEqual(catalog.target_at(QPoint(-800,75),level=100).kind,'window')

    def test_button_boundary_takes_precedence_over_text_inside_button(self):
        catalog=WindowCatalog([ScreenMapping('s',QRect(0,0,1000,800),QRect(0,0,1000,800))],[(1,QRect(0,0,1000,800))])
        catalog.add_regions(1,[('line',QRect(115,115,60,20)),('control',QRect(100,100,100,50))])
        self.assertEqual(catalog.target_at(QPoint(130,125)).native,QRect(100,100,100,50))

    def test_regions_from_covered_windows_are_never_selected(self):
        catalog=WindowCatalog([ScreenMapping('s',QRect(0,0,1000,800),QRect(0,0,1000,800))],[(2,QRect(100,100,300,250)),(1,QRect(0,0,900,700))])
        catalog.add_regions(1,[('line',QRect(120,120,200,25))])
        self.assertEqual(catalog.target_at(QPoint(150,130)).handle,2)


class ElementInteractionChecks(unittest.TestCase):
    setUp=window_checks.WindowDetectionChecks.setUp
    tearDown=window_checks.WindowDetectionChecks.tearDown
    overlay=window_checks.WindowDetectionChecks.overlay

    def test_wheel_changes_hierarchy_and_tab_returns_to_whole_window(self):
        overlay=self.overlay()
        overlay.window_catalog.add_regions(17,[('line',QRect(400,300,350,40)),('paragraph',QRect(390,290,390,180))])
        overlay.set_capture_active(True,overlay.geometry().topLeft()+QPoint(250,160))
        self.assertEqual(overlay.hover_target.kind,'line')
        event=QWheelEvent(QPointF(250,160),QPointF(overlay.mapToGlobal(QPoint(250,160))),QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        app.sendEvent(overlay,event)
        self.assertEqual(overlay.hover_target.kind,'paragraph')
        overlay.show()
        QTest.keyClick(overlay,Qt.Key.Key_Tab)
        self.assertEqual(overlay.hover_target.kind,'window')
        QTest.keyClick(overlay,Qt.Key.Key_Tab)
        self.assertEqual(overlay.hover_target.kind,'line')
        QTest.mouseClick(overlay,Qt.MouseButton.LeftButton,pos=QPoint(250,160))
        self.assertEqual(overlay.canvas.pixmap().width(),350)
        # Subsequent metadata cannot change a committed screenshot.
        canvas=overlay.canvas
        overlay.window_catalog.add_regions(17,[('text',QRect(470,310,50,25))])
        overlay.update_window_preview()
        self.assertIs(overlay.canvas,canvas)
        self.assertIsNone(overlay.hover_target)


if __name__=='__main__':unittest.main()
