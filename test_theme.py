import unittest
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtCore import Qt,QPoint,QCoreApplication,QEvent
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from theme import ThemedComboBox,ThemedFontComboBox,LIGHT_STYLE

app=QApplication.instance() or QApplication([])


class PopupChecks(unittest.TestCase):
    def tearDown(self):
        for widget in app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def create(self):
        available=app.primaryScreen().availableGeometry()
        host=QWidget()
        host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        host.setStyleSheet(LIGHT_STYLE)
        host.setGeometry(available.left()+40,available.top()+40,260,180)
        combo=ThemedComboBox(host)
        combo.setGeometry(20,30,172,32)
        combo.addItems(['复制','贴图','保存'])
        combo.view().window().setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        host.show()
        app.processEvents()
        return host,combo

    def test_selection_does_not_move_popup_or_add_an_extra_frame(self):
        host,combo=self.create()
        positions=[]
        for row in [0,2]:
            combo.setCurrentIndex(row)
            combo.showPopup()
            app.processEvents()
            popup=combo.view().window()
            positions.append(popup.pos())
            self.assertEqual(popup.y(),combo.mapToGlobal(QPoint(0,combo.height())).y()+4)
            self.assertEqual(popup.x(),combo.mapToGlobal(QPoint()).x())
            self.assertEqual(combo.view().verticalScrollBar().maximum(),0)
            self.assertEqual(combo.view().frameWidth(),0)
            image=popup.grab().toImage()
            self.assertEqual(image.pixelColor(2,image.height()//2),QColor('white'))
            self.assertEqual(image.pixelColor(0,0).alpha(),0)
            combo.hidePopup()
        self.assertEqual(positions[0],positions[1])

    def test_keyboard_selection_commits_once_and_escape_cancels(self):
        host,combo=self.create()
        activated=[]
        combo.activated.connect(activated.append)
        combo.showPopup()
        QTest.keyClick(combo.view(),Qt.Key.Key_Down)
        QTest.keyClick(combo.view(),Qt.Key.Key_Down)
        QTest.keyClick(combo.view(),Qt.Key.Key_Return)
        self.assertEqual(combo.currentIndex(),2)
        self.assertEqual(activated,[2])
        self.assertFalse(combo.view().window().isVisible())
        combo.showPopup()
        QTest.keyClick(combo.view(),Qt.Key.Key_Up)
        QTest.keyClick(combo.view(),Qt.Key.Key_Escape)
        self.assertEqual(combo.currentIndex(),2)
        self.assertEqual(activated,[2])

    def test_screen_bottom_flips_up_and_right_edge_stays_visible(self):
        host,combo=self.create()
        available=app.primaryScreen().availableGeometry().adjusted(4,4,-4,-4)
        host.move(available.right()-100,available.bottom()-90)
        combo.showPopup()
        popup=combo.view().window()
        self.assertTrue(available.contains(popup.geometry()))
        self.assertLess(popup.geometry().bottom(),combo.mapToGlobal(QPoint()).y())
        combo.hidePopup()

    def test_mouse_click_commits_the_clicked_option(self):
        host,combo=self.create()
        combo.showPopup()
        app.processEvents()
        index=combo.model().index(1,0)
        QTest.mouseClick(combo.view().viewport(),Qt.MouseButton.LeftButton,pos=combo.view().visualRect(index).center())
        self.assertEqual(combo.currentText(),'贴图')
        self.assertFalse(combo.view().window().isVisible())

    def test_font_dropdown_keeps_font_selection_working(self):
        host,combo=self.create()
        font=ThemedFontComboBox(host)
        font.setGeometry(20,80,190,32)
        font.view().window().setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        font.showPopup()
        chosen=font.count()-1
        expected=font.itemText(chosen)
        font.view().window().choose(font.model().index(chosen,0))
        self.assertEqual(font.currentText(),expected)
        self.assertEqual(font.currentFont().family(),expected)
        self.assertFalse(font.view().window().isVisible())


if __name__=='__main__':unittest.main()
