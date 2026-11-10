import ctypes
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QPoint, QRect, QSize, QAbstractAnimation
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from delayed_capture import CaptureCountdown, countdown_position

app = QApplication.instance() or QApplication([])


class CountdownChecks(unittest.TestCase):
    def setUp(self):
        self.countdown = CaptureCountdown()

    def tearDown(self):
        self.countdown.dispose()
        self.countdown.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def start(self, seconds=3):
        with patch('delayed_capture.monotonic', return_value=100):
            self.countdown.start(seconds, app.primaryScreen(), 'Ctrl+Shift+4')

    def test_countdown_uses_elapsed_time_and_hides_before_capture(self):
        captures = []
        self.countdown.finished.connect(lambda: captures.append(self.countdown.panel.isVisible()))
        self.start()
        with patch('delayed_capture.monotonic', return_value=102.4):
            self.countdown.tick()
            self.assertEqual(self.countdown.number.text(), '1')
        with patch('delayed_capture.monotonic', return_value=104):
            self.countdown.tick()
        self.assertFalse(self.countdown.panel.isVisible())
        self.assertEqual(captures, [])
        QTest.qWait(180)
        self.assertEqual(captures, [False])
        self.countdown.complete()
        self.assertEqual(captures, [False])

    def test_cancel_during_panel_removal_prevents_late_capture_and_can_restart(self):
        captures, cancellations = [], []
        self.countdown.finished.connect(lambda: captures.append(True))
        self.countdown.cancelled.connect(lambda: cancellations.append(True))
        self.start()
        with patch('delayed_capture.monotonic', return_value=104):
            self.countdown.tick()
        self.countdown.cancel()
        QTest.qWait(180)
        self.assertFalse(self.countdown.running)
        self.assertEqual(captures, [])
        self.assertEqual(cancellations, [True])
        self.start(5)
        self.assertEqual(self.countdown.number.text(), '5')
        self.assertTrue(self.countdown.running)

    def test_panel_does_not_take_foreground_and_allows_mouse_input_through(self):
        before = ctypes.windll.user32.GetForegroundWindow()
        self.start()
        app.processEvents()
        self.assertEqual(ctypes.windll.user32.GetForegroundWindow(), before)
        self.assertTrue(self.countdown.panel.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        self.assertTrue(self.countdown.panel.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        self.assertAlmostEqual(self.countdown.panel.windowOpacity(), 0.78, delta=0.01)
        old = self.countdown.panel.geometry()
        self.countdown.timer.stop()
        with patch('delayed_capture.QCursor.pos', return_value=QPoint(old.right()+20, old.center().y())):
            self.countdown.reposition()
        self.assertEqual(self.countdown.animation.state(), QAbstractAnimation.State.Running)
        self.countdown.animation.setCurrentTime(140)
        destination = self.countdown.animation.endValue()
        total = abs(destination.x() - old.x())
        travelled = abs(self.countdown.panel.x() - old.x())
        self.assertGreater(travelled, total * 0.5)
        self.assertLess(travelled, total)
        self.countdown.animation.setCurrentTime(280)
        app.processEvents()
        self.assertFalse(self.countdown.panel.geometry().intersects(old))
        self.assertEqual(ctypes.windll.user32.GetForegroundWindow(), before)

    def test_avoidance_stays_on_starting_monitor_and_does_not_chase_mouse(self):
        bounds = QRect(-1920, -200, 1920, 1080)
        size = QSize(320, 120)
        initial = countdown_position(bounds, size, QPoint(-1200, 300))
        moved = countdown_position(bounds, size, initial.center(), initial)
        self.assertTrue(bounds.contains(moved))
        self.assertFalse(moved.intersects(QRect(initial.center() - QPoint(40, 40), QSize(81, 81))))
        # Moving to another monitor leaves a safe panel in its existing position.
        self.assertEqual(countdown_position(bounds, size, QPoint(500, 500), moved), moved)

    def test_no_clear_position_hides_panel_until_pointer_leaves(self):
        bounds = QRect(0, 0, 400, 220)
        initial = countdown_position(bounds, QSize(320, 120), bounds.center())
        self.assertIsNone(countdown_position(bounds, QSize(320, 120), bounds.center(), initial))
        self.assertIsNotNone(countdown_position(bounds, QSize(320, 120), QPoint(900, 900), initial))

    def test_centered_compact_card_preserves_digit_size_and_has_shadow(self):
        self.start()
        app.processEvents()
        bounds = app.primaryScreen().availableGeometry()
        self.assertEqual(self.countdown.panel.geometry().center(), bounds.center())
        self.assertLess(self.countdown.panel.width(), 240)
        self.assertEqual(self.countdown.number.font().pixelSize(), 36)
        self.assertGreater(self.countdown.shadow.blurRadius(), 0)

    def test_four_approach_directions_move_to_opposite_edges(self):
        bounds, size = QRect(-1920, -200, 1920, 1080), QSize(196, 118)
        current = countdown_position(bounds, size, bounds.center())
        safe = bounds.adjusted(16, 24, -16, -24)
        cases = [(QPoint(current.right()+20, current.center().y()), 'left', safe.left()),
                 (QPoint(current.left()-20, current.center().y()), 'right', safe.right()),
                 (QPoint(current.center().x(), current.top()-20), 'bottom', safe.bottom()),
                 (QPoint(current.center().x(), current.bottom()+20), 'top', safe.top())]
        for cursor, side, expected in cases:
            with self.subTest(side=side):
                target = countdown_position(bounds, size, cursor, current)
                self.assertEqual(getattr(target, side)(), expected)
                self.assertTrue(bounds.contains(target))
                if side in ['left','right']:self.assertEqual(target.y(), current.y())
                else:self.assertEqual(target.x(), current.x())

    def test_expiry_stops_movement_before_hiding_and_capture(self):
        self.start()
        old = self.countdown.panel.geometry()
        with patch('delayed_capture.QCursor.pos', return_value=QPoint(old.right()+20, old.center().y())):
            self.countdown.reposition()
        self.assertEqual(self.countdown.animation.state(), QAbstractAnimation.State.Running)
        with patch('delayed_capture.monotonic', return_value=104):
            self.countdown.tick()
        self.assertEqual(self.countdown.animation.state(), QAbstractAnimation.State.Stopped)
        self.assertFalse(self.countdown.panel.isVisible())

    def test_delayed_action_starts_configured_countdown_and_repeated_action_cancels(self):
        from app import Home
        countdown = SimpleNamespace(running=False, start=MagicMock(), cancel=MagicMock())
        home = SimpleNamespace(delay_countdown=countdown, capture_pending=False,
                               overlays=[], settings_window=MagicMock(), hide=MagicMock())
        preferences = MagicMock()
        preferences.value.return_value = 7
        with patch('app.preferences', return_value=preferences), patch('app.keys', return_value={7:'F9'}), \
                patch('app.QApplication.screenAt', return_value=app.primaryScreen()):
            Home.delayed_capture(home)
        self.assertTrue(home.capture_pending)
        countdown.start.assert_called_once_with(7, app.primaryScreen(), 'F9')
        home.settings_window.hide.assert_called_once()
        countdown.running = True
        Home.delayed_capture(home)
        countdown.cancel.assert_called_once()
        Home.cancel_delayed_capture(home)
        self.assertFalse(home.capture_pending)


if __name__ == '__main__':
    unittest.main()
