"""Automatic capture: continuous pulses, overlap, end detection and final tail."""
import time
import unittest
from unittest.mock import patch,Mock
import numpy as np
from PySide6.QtCore import Qt,QRect,QCoreApplication,QEvent,QObject,Signal
from PySide6.QtGui import QPixmap,QColor
from PySide6.QtWidgets import QApplication,QStyle,QToolButton,QWidget
from scroll_capture import ScrollCapture,AutoWheelPump
from theme import TooltipStyle

app=QApplication.instance() or QApplication([])


class SimulatedPump(QObject):
    failed=Signal(object)

    def __init__(self,point,sign,horizontal,target,rate):
        super().__init__()
        self.point,self.sign,self.horizontal,self.target=point,sign,horizontal,target
        self.rate,self.total_sent,self.remainder=rate,0,0
        self.stopped=False

    def start(self):pass
    def stop(self):self.stopped=True
    def set_rate(self,rate):self.rate=rate
    def stats(self):return self.total_sent,self.rate

    def advance(self,seconds):
        from scroll_capture import send_region_wheel
        if self.stopped:return
        for _ in range(round(seconds/.016)):
            self.remainder+=self.rate*.016
            delta=int(self.remainder)
            if not delta:continue
            self.remainder-=delta
            if send_region_wheel(self.point,self.sign*delta,self.horizontal,self.target) is None:
                self.stopped=True
                self.failed.emit(self)
                return
            self.total_sent+=delta


class AutoScrollChecks(unittest.TestCase):
    def setUp(self):
        self.producer=patch('scroll_capture.AutoWheelPump',SimulatedPump)
        self.producer.start()

    def tearDown(self):
        self.producer.stop()
        for widget in app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def create(self,index=0):
        screen=app.primaryScreen()
        frozen=QPixmap(screen.size())
        frozen.fill(QColor('white'))
        capture=ScrollCapture(None,screen,QRect(120,160,350,320),frozen)
        capture.direction.setCurrentIndex(index)
        capture.test_time=time.monotonic()
        return capture

    def advance(self,capture):
        capture.test_time+=.11
        with patch('scroll_capture.time.monotonic',return_value=capture.test_time):
            if capture.auto_pump is not None:capture.auto_pump.advance(.11)
            capture.tick()
            self.drain(capture)

    def drain(self,capture):
        for _ in range(13):
            if not capture.auto_settling:break
            capture.test_time+=.08
            with patch('scroll_capture.time.monotonic',return_value=capture.test_time):capture.finish_auto_stop()

    def test_four_directions_capture_complete_document_and_stop_at_end(self):
        content=np.random.default_rng(66).integers(0,256,(800,180,3),dtype=np.uint8)
        for index in range(4):
            with self.subTest(direction=index):
                c=self.create(index)
                position=[480 if c.reverse else 0]
                def frame():
                    result=content[position[0]:position[0]+320].copy()
                    return result if c.vertical else result.transpose(1,0,2)
                c.previous=frame()
                c.parts=[c.previous]
                pulses=[]
                def wheel(point,delta,horizontal,root):
                    pulses.append((delta,horizontal,root))
                    self.assertEqual(horizontal,not c.vertical)
                    sign=(1 if c.reverse else -1) if c.vertical else (-1 if c.reverse else 1)
                    self.assertEqual(1 if delta>0 else -1,sign)
                    position[0]=max(0,min(480,position[0]+(-1 if c.reverse else 1)*abs(delta)*2))
                    return 123
                with patch('scroll_capture.send_region_wheel',side_effect=wheel),patch.object(c,'grab',side_effect=frame):
                    c.toggle_auto()
                    for _ in range(150):
                        if not c.automatic:break
                        self.advance(c)
                    self.assertFalse(c.automatic)
                    expected=content if c.vertical else content.transpose(1,0,2)
                    np.testing.assert_array_equal(c.full_frame(),expected)
                    self.assertIn('不再滚动',c.tip.text())
                    self.assertIsNone(pulses[0][2])
                    self.assertTrue(all(pulse[2]==123 for pulse in pulses[1:]))
                    self.assertLessEqual(max(abs(pulse[0]) for pulse in pulses),4)
                c.cancel()

    def test_apps_accumulating_partial_notches_do_not_stop_early(self):
        c=self.create()
        content=np.random.default_rng(77).integers(0,256,(440,180,3),dtype=np.uint8)
        state={'offset':0,'wheel':0}
        def frame():return content[state['offset']:state['offset']+320].copy()
        def wheel(*args):
            state['wheel']+=abs(args[1])
            if state['wheel']>=120:
                state['offset']=min(120,state['offset']+60)
                state['wheel']-=120
            return 123
        c.previous=frame()
        c.parts=[c.previous]
        with patch('scroll_capture.send_region_wheel',side_effect=wheel),patch.object(c,'grab',side_effect=frame):
            c.toggle_auto()
            for _ in range(150):
                if not c.automatic:break
                self.advance(c)
            self.assertFalse(c.automatic)
            np.testing.assert_array_equal(c.full_frame(),content)

    def test_unreliable_frame_pauses_motion_and_keeps_last_good_image(self):
        c=self.create()
        data=np.random.default_rng(8).integers(0,256,(2,320,180,3),dtype=np.uint8)
        c.previous=data[0]
        c.parts=[c.previous]
        with patch('scroll_capture.send_region_wheel',return_value=123) as send,patch.object(c,'grab',return_value=data[1]):
            c.toggle_auto()
            self.advance(c)
            count=send.call_count
            self.assertEqual(c.auto_pump.rate,0)
            for _ in range(14):self.advance(c)
            self.assertFalse(c.automatic)
            self.assertEqual(send.call_count,count)
            np.testing.assert_array_equal(c.full_frame(),data[0])

    def test_stop_and_copy_include_the_last_scrolled_tail(self):
        c=self.create()
        content=np.random.default_rng(14).integers(0,256,(600,180,3),dtype=np.uint8)
        position=[0]
        c.previous=content[:320]
        c.parts=[c.previous]
        c.controller=Mock()
        def frame():return content[position[0]:position[0]+320].copy()
        def wheel(*args):
            position[0]+=abs(args[1])
            return 123
        with patch('scroll_capture.send_region_wheel',side_effect=wheel),patch.object(c,'grab',side_effect=frame):
            c.toggle_auto()
            self.advance(c)
            c.auto_pump.advance(.11)
            c.complete('copy')
            self.assertTrue(c.auto_settling)
            c.controller.captured.assert_not_called()
            self.drain(c)
            np.testing.assert_array_equal(c.full_frame(),content[:320+position[0]])
            c.controller.captured.assert_called_once()
            self.assertTrue(c.finished)

    def test_pause_direction_cancel_and_close_stop_producer(self):
        for action in ['pause','direction','cancel','close']:
            with self.subTest(action=action):
                c=self.create()
                with patch('scroll_capture.send_region_wheel',return_value=123),patch.object(c,'grab',return_value=np.zeros((320,180,3),np.uint8)):
                    c.toggle_auto()
                    producer=c.auto_pump
                    if action=='direction':c.direction.setCurrentIndex(1)
                    else:getattr(c,action)()
                    self.assertFalse(c.automatic)
                    self.assertTrue(producer.stopped)
                    self.assertEqual(c.settle_timer.isActive(),action=='pause')

    def test_target_change_stops_and_stale_failure_does_not_stop_new_session(self):
        c=self.create()
        with patch('scroll_capture.send_region_wheel',return_value=123):
            c.toggle_auto()
            previous=c.auto_pump
            c.stop_auto()
            c.toggle_auto()
            c.auto_target_failed(previous)
            self.assertTrue(c.automatic)
            c.auto_target_failed(c.auto_pump)
            self.assertFalse(c.automatic)
            self.assertIn('目标窗口',c.tip.text())

    def test_native_producer_keeps_pulsing_during_slow_frame_processing(self):
        received=[]
        pump=AutoWheelPump(app.primaryScreen().geometry().center(),-1,False,123,120)
        with patch('scroll_capture.send_region_wheel',side_effect=lambda *args:received.append(args[1]) or 123):
            pump.start()
            try:time.sleep(.26)
            finally:pump.stop()
            count=len(received)
            time.sleep(.05)
        self.assertGreaterEqual(count,8)
        self.assertEqual(len(received),count)
        self.assertLessEqual(max(map(abs,received)),4)

    def test_every_scroll_toolbar_icon_has_a_name_and_tooltip_delay(self):
        c=self.create()
        for button in c.bar.findChildren(QToolButton):
            if not button.icon().isNull():self.assertTrue(button.toolTip())
        style=TooltipStyle()
        self.assertEqual(style.styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay),2000)
        self.assertEqual(style.styleHint(QStyle.StyleHint.SH_ToolTip_FallAsleepDelay),0)

    def test_live_mask_has_only_translucent_shading_after_frozen_cover(self):
        c=self.create()
        self.assertTrue(c.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        c.transition_cover=True
        c.apply_mask()
        # Render the transition and then reuse the same widget/backing store.
        # No opaque pixels from the frozen desktop may survive the transition.
        before=QWidget.grab(c).toImage().pixelColor(20,20)
        self.assertEqual(before.alpha(),255)
        c.transition_cover=False
        c.apply_mask()
        after=QWidget.grab(c).toImage().pixelColor(20,20)
        self.assertEqual(after.alpha(),80)
        self.assertEqual(after.red(),0)
        self.assertFalse(c.mask().contains(c.region.center()))


if __name__=='__main__':unittest.main()
