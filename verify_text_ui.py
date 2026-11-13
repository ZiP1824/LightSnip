"""Exercise the screenshot text workflow inside the packaged Qt runtime."""
from PySide6.QtCore import QPoint, QRect, Qt, QCoreApplication, QEvent
from PySide6.QtGui import QColor, QInputMethodEvent, QPixmap, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def verify_text_workflow(overlay_type, cycles=20):
    app = QApplication.instance()
    screen = app.primaryScreen()
    frozen = QPixmap(screen.geometry().size())
    frozen.fill(QColor('white'))
    overlay = overlay_type(screen, frozen)
    overlay.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    overlay.show()
    try:
        verify_multiple_text_marks(overlay)
        for cycle in range(cycles):
            overlay.set_selection(QRect(40, 40, 460, 220))
            overlay.tool('文字')
            canvas = overlay.canvas
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(45, 70))
            field = canvas.text_editor
            field.insertPlainText('中文')
            app.processEvents()
            width = field.width()
            height = field.height()
            app.sendEvent(field, QInputMethodEvent('zhongwen', []))
            app.processEvents()
            assert field.width() > width and field.composing and field.height() == height
            assert field.document().firstBlock().layout().lineCount() == 1
            commit = QInputMethodEvent('', [])
            commit.setCommitString('文字测试')
            app.sendEvent(field, commit)
            app.processEvents()
            assert field.width() > width and not field.composing
            edge = QPoint(field.width() // 2, 0)
            origin = field.pos()
            QTest.mousePress(field, Qt.MouseButton.LeftButton, pos=edge)
            QTest.mouseMove(field, edge + QPoint(25, 15))
            QTest.mouseRelease(field, Qt.MouseButton.LeftButton, pos=edge)
            assert field.pos() == origin + QPoint(25, 15)
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(420, 150))
            assert canvas.text_marks[0].text == '中文文字测试'
            point = canvas.text_marks[0].rect().center()
            overlay.tool('选区')
            QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=canvas.pos()+point)
            QTest.mouseDClick(overlay, Qt.MouseButton.LeftButton, pos=canvas.pos()+point)
            assert canvas.text_editor.toPlainText() == '中文文字测试'
            QTest.keyClick(canvas.text_editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            overlay.options.set_color(QColor('#2244bb'))
            overlay.tool('箭头')
            app.processEvents()
            assert canvas.text_marks[0].text == '中文文字测试'
            assert canvas.pixmap().toImage() != canvas.image
            if cycle % 4 == 0:
                overlay.tool('文字')
                mark=canvas.text_marks[0]
                point=mark.rect().center()
                QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=point)
                QTest.mouseMove(canvas,point+QPoint(12,8))
                QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=point+QPoint(12,8))
                assert canvas.text_marks[0].position==mark.position+QPoint(12,8)
                handle=canvas.text_handle().center()
                QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=handle)
                QTest.mouseMove(canvas,handle+QPoint(16,10))
                QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=handle+QPoint(16,10))
                assert canvas.text_marks[0].scale>1
                canvas.undo()
                assert canvas.text_marks[0].scale==1
                canvas.redo()
                assert canvas.text_marks[0].scale>1
                overlay.tool('选区')
                overlay.set_selection(QRect(45,45,455,215),keep_text=True)
                assert overlay.canvas.text_marks[0].text=='中文文字测试'
            if cycle % 5 == 0:
                overlay.canvas.grab()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return cycles
    finally:
        overlay.close()
        overlay.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def verify_number_workflow(overlay_type):
    screen=QApplication.primaryScreen()
    frozen=QPixmap(screen.geometry().size())
    frozen.fill(QColor('white'))
    overlay=overlay_type(screen,frozen)
    overlay.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    overlay.show()
    try:
        overlay.set_selection(QRect(40,40,460,240))
        overlay.tool('序号')
        canvas=overlay.canvas
        points=[QPoint(x,60) for x in (45,110,175,240)]
        for point in points:
            QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=point)
        assert [mark.number for mark in canvas.number_marks]==[1,2,3,4]
        QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=points[2])
        assert overlay.options.delete_number_button.isVisible()
        QTest.mouseClick(overlay.options.delete_number_button,Qt.MouseButton.LeftButton)
        assert [mark.number for mark in canvas.number_marks]==[1,2,4]
        assert canvas.pixmap().toImage().pixelColor(points[2])==QColor('white')
        canvas.undo()
        assert [mark.number for mark in canvas.number_marks]==[1,2,3,4]
        canvas.redo()
        assert [mark.number for mark in canvas.number_marks]==[1,2,4]
        QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=QPoint(175,130))
        assert [mark.number for mark in canvas.number_marks]==[1,2,4,3]
        QTest.keyClick(canvas,Qt.Key.Key_Delete)
        QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=QPoint(175,160))
        QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=QPoint(240,160))
        assert [mark.number for mark in canvas.number_marks]==[1,2,4,3,5]
        overlay.clear_marks()
        QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=points[0])
        assert [mark.number for mark in canvas.number_marks]==[1]
    finally:
        overlay.close()
        overlay.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def verify_multiple_text_marks(overlay, click=None):
    if click is None:
        click=lambda widget,point:QTest.mouseClick(widget,Qt.MouseButton.LeftButton,pos=point)
    overlay.set_selection(QRect(40,40,460,240))
    overlay.tool('文字')
    canvas=overlay.canvas
    labels=['第一条文字','第二条文字','第三条文字']
    for point,label in zip([QPoint(45,30),QPoint(45,95),QPoint(45,155)],labels):
        QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=point)
        canvas.text_editor.setPlainText(label)
        QTest.keyClick(canvas.text_editor,Qt.Key.Key_Return,Qt.KeyboardModifier.ControlModifier)
    assert [mark.text for mark in canvas.text_marks]==labels

    # Starting a fourth entry must not swallow the click on an earlier mark.
    canvas.begin_text(QPoint(245,155))
    canvas.text_editor.setPlainText('第四条文字')
    first=canvas.text_marks[0].rect().center()
    QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=first)
    assert canvas.selected_text==0
    QTest.mouseDClick(canvas,Qt.MouseButton.LeftButton,pos=first)
    assert canvas.text_editor.toPlainText()==labels[0]
    canvas.cancel_text()

    # The list can target a covered mark independently of canvas hit testing.
    from dataclasses import replace
    canvas.text_marks[1]=replace(canvas.text_marks[1],position=canvas.text_marks[0].position)
    assert canvas.text_at(first)==1
    canvas.selected_text=0
    QTest.keyClick(canvas,Qt.Key.Key_F2)
    assert canvas.text_editor.toPlainText()==labels[0]
    canvas.cancel_text()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    button=overlay.options.edit_text_button
    listing=overlay.options.text_list
    click(button,button.rect().center())
    QApplication.processEvents()
    assert listing.isVisible(),'编辑文字按钮没有打开列表'
    assert listing.count()==4 and labels[0] in listing.item(0).text()
    click(listing.viewport(),listing.visualItemRect(listing.item(0)).center())
    QApplication.processEvents()
    assert not listing.isVisible()
    assert canvas.text_editor.toPlainText()==labels[0]
    editor=canvas.text_editor
    # Reopening places the cursor before the first saved run. Typing there
    # used to pick up the UI theme's small font.
    expected_size=canvas.text_font(canvas.width()/canvas.image.width()).pointSizeF()
    assert abs(editor.currentCharFormat().fontPointSize()-expected_size)<0.1
    QTest.keyClicks(editor,'123')
    assert abs(editor.document().find('123').charFormat().fontPointSize()-expected_size)<0.1
    editor.moveCursor(QTextCursor.MoveOperation.End)
    QTest.keyClicks(editor,'XYZ')
    assert abs(editor.document().find('XYZ').charFormat().fontPointSize()-expected_size)<0.1
    QTest.keyClick(editor,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
    replacement=QInputMethodEvent('',[])
    replacement.setCommitString('第一条已修改')
    QApplication.sendEvent(editor,replacement)
    assert abs(editor.document().find('第一条已修改').charFormat().fontPointSize()-expected_size)<0.1
    QTest.keyClick(canvas.text_editor,Qt.Key.Key_Return,Qt.KeyboardModifier.ControlModifier)
    assert [mark.text for mark in canvas.text_marks]==['第一条已修改',*labels[1:],'第四条文字']
    canvas.undo()
    assert canvas.text_marks[0].text==labels[0]
    canvas.redo()
    assert canvas.text_marks[0].text=='第一条已修改'


def verify_native_text_list(overlay_type):
    import ctypes
    from PySide6.QtGui import QCursor
    app=QApplication.instance()
    original_cursor=QCursor.pos()
    verified=0

    def click(widget,point):
        target=widget.mapToGlobal(point)
        QTest.qWait(70)
        QCursor.setPos(target)
        actual=app.widgetAt(target)
        assert actual is widget or (actual is not None and widget.isAncestorOf(actual))
        ctypes.windll.user32.mouse_event(2,0,0,0,0)
        QTest.qWait(25)
        QCursor.setPos(target)
        ctypes.windll.user32.mouse_event(4,0,0,0,0)
        QTest.qWait(70)

    try:
        for screen in app.screens():
            frozen=QPixmap(screen.geometry().size())
            frozen.fill(QColor('white'))
            overlay=overlay_type(screen,frozen)
            try:
                overlay.show()
                overlay.activateWindow()
                QTest.qWait(100)
                verify_multiple_text_marks(overlay,click)
                verified+=1
            finally:
                overlay.close()
                overlay.deleteLater()
                QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            QTest.qWait(550)
        return verified
    finally:
        QCursor.setPos(original_cursor)
