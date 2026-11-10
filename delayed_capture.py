"""Visible, non-activating countdown for capturing transient menus."""
import math
from time import monotonic
from PySide6.QtCore import QObject, Qt, QTimer, Signal, QRect, QPropertyAnimation, QEasingCurve, QAbstractAnimation
from PySide6.QtGui import QCursor, QColor
from PySide6.QtWidgets import QWidget, QFrame, QLabel, QVBoxLayout, QGraphicsDropShadowEffect


def countdown_position(bounds, size, cursor, current=None, previous_cursor=None):
    """Start centered, then escape to the opposite edge of the approaching pointer."""
    safe = bounds.adjusted(16, 24, -16, -24)
    if size.width() > safe.width() or size.height() > safe.height():
        return None
    if current is None:
        centered = QRect(safe.topLeft(), size)
        centered.moveCenter(bounds.center())
        return centered
    pointer_area = QRect(cursor.x() - 40, cursor.y() - 40, 81, 81)
    if safe.contains(current) and not current.intersects(pointer_area):
        return current
    left, right = safe.left(), safe.right() - size.width() + 1
    top, bottom = safe.top(), safe.bottom() - size.height() + 1
    x = max(left, min(current.left(), right))
    y = max(top, min(current.top(), bottom))
    destinations = {'left': (left, y), 'right': (right, y),
                    'top': (x, top), 'bottom': (x, bottom)}
    approach = cursor
    if abs(cursor.x() - current.center().x()) + abs(cursor.y() - current.center().y()) < 8:
        approach = previous_cursor if previous_cursor is not None else cursor
    dx = (approach.x() - current.center().x()) / max(1, current.width())
    dy = (approach.y() - current.center().y()) / max(1, current.height())
    preferred = ('left' if dx > 0 else 'right') if abs(dx) >= abs(dy) else ('top' if dy > 0 else 'bottom')
    candidates = {name: QRect(px, py, size.width(), size.height())
                  for name, (px, py) in destinations.items()}
    preferred_rect = candidates[preferred]
    if not preferred_rect.intersects(pointer_area):
        return preferred_rect
    # At an edge, use a different clear edge rather than oscillating in place.
    candidates = list(candidates.values())
    clear = [rect for rect in candidates if not rect.intersects(pointer_area)]
    if not clear:
        return None
    return max(clear, key=lambda rect: (rect.center().x() - cursor.x()) ** 2 +
                                      (rect.center().y() - cursor.y()) ** 2)


class CaptureCountdown(QObject):
    finished = Signal()
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.deadline = 0
        self.panel = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                             Qt.WindowType.WindowStaysOnTopHint |
                             Qt.WindowType.WindowDoesNotAcceptFocus |
                             Qt.WindowType.WindowTransparentForInput)
        self.panel.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.panel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.panel.setWindowOpacity(0.78)
        self.panel.setWindowTitle('轻截 · 延时截图')
        outer = QVBoxLayout(self.panel)
        outer.setContentsMargins(14, 14, 14, 20)
        card = QFrame()
        card.setObjectName('countdownCard')
        card.setStyleSheet('QFrame#countdownCard {background:#ffffff;border:1px solid #c4c9df;border-radius:12px;} '
                          'QLabel {background:transparent;border:0;color:#263449;font-size:12px;} '
                          'QLabel#seconds {font-size:36px;font-weight:700;color:#6059da;} '
                          'QLabel#hint {font-size:11px;color:#475569;}')
        self.shadow = QGraphicsDropShadowEffect(card)
        self.shadow.setBlurRadius(20)
        self.shadow.setOffset(0, 4)
        self.shadow.setColor(QColor(25, 35, 60, 175))
        card.setGraphicsEffect(self.shadow)
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(0)
        title = QLabel('延时截图')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self.number = QLabel()
        self.number.setObjectName('seconds')
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.number)
        self.hint = QLabel()
        self.hint.setObjectName('hint')
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.tick)
        # Give the compositor time to remove the panel before freezing the desktop.
        self.capture_timer = QTimer(self)
        self.capture_timer.setSingleShot(True)
        self.capture_timer.setInterval(100)
        self.capture_timer.timeout.connect(self.complete)
        self.animation = QPropertyAnimation(self.panel, b'pos', self)
        self.animation.setDuration(280)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.previous_cursor = None

    def start(self, seconds, screen, shortcut=''):
        if self.running:
            return
        seconds = max(1, min(60, int(seconds)))
        self.running = True
        self.deadline = monotonic() + seconds
        self.number.setText(str(seconds))
        self.animation.stop()
        self.hint.setText(f'{shortcut} 取消' if shortcut else '准备框选')
        bounds = screen.availableGeometry()
        self.bounds = QRect(bounds)
        self.panel.setFixedWidth(min(196, max(120, bounds.width() - 32)))
        self.panel.adjustSize()
        self.reposition(initial=True)
        self.timer.start()

    def reposition(self, initial=False):
        cursor = QCursor.pos()
        if not initial and self.animation.state() == QAbstractAnimation.State.Running:
            self.previous_cursor = cursor
            return
        current = None if initial else self.panel.geometry()
        target = countdown_position(self.bounds, self.panel.size(), cursor, current, self.previous_cursor)
        self.previous_cursor = cursor
        if target is None:
            self.animation.stop()
            self.panel.hide()
            return
        if self.panel.pos() != target.topLeft():
            if initial or not self.panel.isVisible():
                self.panel.move(target.topLeft())
            else:
                self.animation.setStartValue(self.panel.pos())
                self.animation.setEndValue(target.topLeft())
                self.animation.start()
        if not self.panel.isVisible():
            self.panel.show()

    def tick(self):
        if not self.running:
            return
        remaining = max(0, math.ceil(self.deadline - monotonic()))
        if remaining:
            self.number.setText(str(remaining))
            self.reposition()
            return
        self.timer.stop()
        self.animation.stop()
        self.panel.hide()
        self.capture_timer.start()

    def complete(self):
        if self.running:
            self.running = False
            self.finished.emit()

    def cancel(self):
        if not self.running:
            return
        self.running = False
        self.timer.stop()
        self.animation.stop()
        self.capture_timer.stop()
        self.panel.hide()
        self.cancelled.emit()

    def dispose(self):
        self.cancel()
        self.panel.close()
        self.panel.deleteLater()
