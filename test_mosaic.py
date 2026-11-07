import unittest
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent,QCoreApplication
from PySide6.QtGui import QPixmap,QColor,QPainter,QImage,QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import Canvas,Editor
from annotation_tools import PreviewSelector

app=QApplication.instance() or QApplication([])


class MosaicChecks(unittest.TestCase):
    def tearDown(self):
        for widget in app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def canvas(self):
        image=QImage(280,220,QImage.Format.Format_RGB32)
        for y in range(image.height()):
            for x in range(image.width()):image.setPixelColor(x,y,QColor(20,20,20) if (x+y)%2 else QColor(235,235,235))
        canvas=Canvas(QPixmap.fromImage(image))
        canvas.mode='马赛克'
        canvas.mosaic_style='画笔涂抹'
        canvas.mosaic_width=30
        canvas.block_size=14
        return canvas

    def stroke(self,canvas,points):
        QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=points[0])
        for point in points[1:-1]:
            event=QMouseEvent(QEvent.Type.MouseMove,QPointF(point),QPointF(point),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
            app.sendEvent(canvas,event)
        QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=points[-1])

    def test_curved_brush_changes_only_its_path_including_fast_release_segment(self):
        canvas=self.canvas()
        original=canvas.image.copy()
        self.stroke(canvas,[QPoint(40,40),QPoint(220,40),QPoint(220,170)])
        for point in [QPoint(40,40),QPoint(120,40),QPoint(220,110),QPoint(220,170)]:
            self.assertNotEqual(canvas.image.pixelColor(point),original.pixelColor(point))
        for point in [QPoint(120,110),QPoint(40,170),QPoint(5,5)]:
            self.assertEqual(canvas.image.pixelColor(point),original.pixelColor(point))

    def test_single_click_width_and_undo_redo(self):
        canvas=self.canvas()
        original=canvas.image.copy()
        self.stroke(canvas,[QPoint(100,100),QPoint(100,100)])
        thin=canvas.image.copy()
        self.assertNotEqual(thin.pixelColor(100,100),original.pixelColor(100,100))
        self.assertEqual(thin.pixelColor(100,125),original.pixelColor(100,125))
        self.assertEqual(len(canvas.undo_stack),1)
        canvas.undo()
        self.assertEqual(canvas.image,original)
        canvas.redo()
        self.assertEqual(canvas.image,thin)
        canvas.undo()
        canvas.mosaic_width=80
        self.stroke(canvas,[QPoint(100,100),QPoint(100,100)])
        self.assertNotEqual(canvas.image.pixelColor(100,125),original.pixelColor(100,125))

    def test_preview_matches_committed_stroke_and_grain_changes_result(self):
        canvas=self.canvas()
        QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=QPoint(30,70))
        canvas.end=QPoint(230,70)
        canvas.stroke.append(canvas.end)
        preview=canvas.image.copy()
        painter=QPainter(preview)
        canvas.draw(painter)
        painter.end()
        QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=QPoint(230,70))
        self.assertEqual(canvas.image,preview)
        self.assertEqual(len(canvas.undo_stack),1)
        # A gradient gives different block samples for different grain settings.
        for x in range(280):
            for y in range(220):canvas.image.setPixelColor(x,y,QColor(x%256,y%256,120))
        canvas.mosaic_style='矩形框选'
        canvas.block_size=8
        self.stroke(canvas,[QPoint(30,30),QPoint(220,180)])
        small=canvas.image.copy()
        canvas.undo()
        canvas.block_size=32
        self.stroke(canvas,[QPoint(30,30),QPoint(220,180)])
        self.assertNotEqual(canvas.image,small)

    def test_rectangle_is_preserved_and_style_slider_use_shared_selector(self):
        canvas=self.canvas()
        original=canvas.image.copy()
        canvas.mosaic_style='矩形框选'
        self.stroke(canvas,[QPoint(30,30),QPoint(130,130)])
        self.assertNotEqual(canvas.image.pixelColor(60,100),original.pixelColor(60,100))
        self.assertEqual(canvas.image.pixelColor(150,100),original.pixelColor(150,100))
        editor=Editor(QPixmap.fromImage(original),None)
        editor.select('马赛克')
        options=editor.options
        self.assertIsInstance(options.mosaic_choice,PreviewSelector)
        self.assertTrue(options.mosaic_brush_widget.isHidden())
        options.mosaic_choice.setCurrentText('画笔涂抹')
        self.assertEqual(editor.canvas.mosaic_style,'画笔涂抹')
        self.assertFalse(options.mosaic_brush_widget.isHidden())
        options.mosaic_brush_widget.control.setValue(72)
        options.mosaic_widget.control.setValue(22)
        self.assertEqual(editor.canvas.mosaic_width,72)
        self.assertEqual(editor.canvas.block_size,22)
        editor.select('箭头')
        self.assertTrue(options.mosaic_choice.isHidden())
        editor.select('马赛克')
        self.assertEqual(editor.canvas.mosaic_width,72)
        self.assertEqual(editor.canvas.mosaic_style,'画笔涂抹')


if __name__=='__main__':unittest.main()
