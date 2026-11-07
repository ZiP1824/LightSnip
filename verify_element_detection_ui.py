import json
import multiprocessing
import time
from pathlib import Path
from PySide6.QtCore import Qt,QPoint,QTimer
from PySide6.QtWidgets import QApplication,QMainWindow,QWidget,QLabel,QLineEdit,QPushButton
from window_detection import snapshot_windows
from element_detection import RegionScanner


def main(output_folder=None,overlay_class=None):
    if overlay_class is None:
        from app import Overlay
        overlay_class=Overlay
    app=QApplication([])
    app.setStyle('Fusion')
    fixture=QMainWindow()
    fixture.setWindowTitle('LightSnip element verification')
    fixture.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    fixture.setGeometry(300,150,940,580)
    content=QWidget()
    content.setStyleSheet('background:white;color:#111;')
    fixture.setCentralWidget(content)
    title=QLabel('A sentence that can be selected automatically.',content)
    title.setGeometry(40,40,830,50)
    title.setStyleSheet('font-size:24px;')
    paragraph=QLabel('Paragraph detection keeps these lines together.\nThe second line belongs to the same paragraph.\nA third line confirms the complete text block.',content)
    paragraph.setGeometry(40,140,800,110)
    paragraph.setStyleSheet('font-size:20px;')
    field=QLineEdit('Editable input boundary',content)
    field.setGeometry(40,340,500,44)
    button=QPushButton('A complete button',content)
    button.setGeometry(40,430,240,48)
    fixture.show()
    state={}
    output=Path(output_folder) if output_folder is not None else Path(__file__).parent/'verification'
    output.mkdir(parents=True,exist_ok=True)
    start=time.monotonic()

    def begin():
        screen=fixture.screen()
        catalog=snapshot_windows(app.screens())
        target=catalog.target_at(fixture.mapToGlobal(QPoint(470,290)))
        assert target.handle==int(fixture.winId())
        frozen=screen.grabWindow(0)
        scanner=RegionScanner(catalog)
        scanner.ensure(target,frozen)
        state.update(catalog=catalog,target=target,frozen=frozen,scanner=scanner,screen=screen)
        timer.start(80)

    def check():
        scanner=state['scanner']
        if scanner.active_jobs and time.monotonic()-start<14:return
        timer.stop()
        report={}
        try:
            regions=state['catalog'].regions.get(int(fixture.winId()),[])
            controls=[r for kind,r in regions if kind=='control']
            lines=[r for kind,r in regions if kind=='line']
            paragraphs=[r for kind,r in regions if kind=='paragraph']
            field_point=state['target'].mapping.native_point(field.mapToGlobal(field.rect().center()))
            assert any(r.contains(field_point) and abs(r.width()-field.width())<10 for r in controls),'Missing input control boundary'
            assert lines,'Missing detected text lines'
            assert paragraphs,'Missing detected paragraph'
            point=title.mapToGlobal(QPoint(240,25))
            targets=state['catalog'].candidates_at(point)
            assert targets and targets[0].native.width()<state['target'].native.width(),'Title still selects the entire window'
            overlay=overlay_class(state['screen'],state['frozen'],window_catalog=state['catalog'])
            overlay.set_window_detection(True)
            overlay.set_capture_active(True,point)
            target=overlay.hover_target
            overlay.set_selection(overlay.target_rect(target),target)
            overlay.canvas.pixmap().save(str(output/'element-selected-line-v22.png'))
            overlay.hints.grab().save(str(output/'element-hints-v22.png'))
            report.update(ok=True,controls=len(controls),lines=len(lines),paragraphs=len(paragraphs),
                          hierarchy=[t.kind for t in targets],seconds=round(time.monotonic()-start,2))
            overlay.close()
            overlay.deleteLater()
        except Exception as exc:report.update(ok=False,error=str(exc))
        scanner.stop()
        (output/'element-detection-v22.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
        state['report']=report
        fixture.close()
        app.quit()

    timer=QTimer()
    timer.timeout.connect(check)
    QTimer.singleShot(300,begin)
    app.exec()
    assert state['report'].get('ok'),state['report']


if __name__=='__main__':
    multiprocessing.freeze_support()
    main()
