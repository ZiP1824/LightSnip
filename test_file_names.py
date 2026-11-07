import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap,QColor,QImage
import file_names

app=QApplication.instance() or QApplication([])


class FilenameChecks(unittest.TestCase):
    def test_many_captures_in_same_instant_and_clock_rollback(self):
        with patch('file_names.datetime') as clock,patch('file_names._last_time',None):
            clock.now.return_value=datetime(2026,11,6,15,30,12,123456)
            names=[file_names.capture_filename() for _ in range(1000)]
            self.assertEqual(names[0],'轻截-20261106-153012-123456.png')
            self.assertEqual(len(set(names)),1000)
            clock.now.return_value=datetime(2026,11,6,15,30,11)
            self.assertNotIn(file_names.capture_filename(),names)

    def test_parallel_name_requests_are_unique(self):
        with patch('file_names.datetime') as clock,patch('file_names._last_time',None):
            clock.now.return_value=datetime(2026,11,6,15,30,12)
            with ThreadPoolExecutor(max_workers=8) as pool:
                names=list(pool.map(lambda _:file_names.capture_filename(),range(200)))
            self.assertEqual(len(set(names)),200)

    def test_existing_screenshot_is_preserved_and_new_pngs_decode(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder,patch('file_names.datetime') as clock,patch('file_names._last_time',None):
            clock.now.return_value=datetime(2026,11,6,15,30,12)
            existing=Path(folder)/'轻截-20261106-153012-000000.png'
            existing.write_bytes(b'existing screenshot')
            pix=QPixmap(80,50)
            pix.fill(QColor('#6059da'))
            paths=[file_names.save_new_png(pix,folder) for _ in range(3)]
            self.assertEqual(existing.read_bytes(),b'existing screenshot')
            self.assertEqual(len(set(paths)),3)
            for path in paths:
                self.assertEqual(QImage(str(path)).pixelColor(20,20),QColor('#6059da'))

    def test_exclusive_creation_recovers_from_another_process_race(self):
        original_open=Path.open
        raced=[]
        def open_with_race(path,mode='r',*args,**kwargs):
            if mode=='xb' and not raced:
                raced.append(path)
                with original_open(path,'wb') as stream:stream.write(b'other process screenshot')
                raise FileExistsError()
            return original_open(path,mode,*args,**kwargs)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder,patch('file_names.datetime') as clock,patch('file_names._last_time',None):
            clock.now.return_value=datetime(2026,11,6,15,30,12)
            pix=QPixmap(80,50)
            pix.fill(QColor('white'))
            with patch.object(Path,'open',open_with_race):path=file_names.save_new_png(pix,folder)
            self.assertNotEqual(path,raced[0])
            self.assertEqual(raced[0].read_bytes(),b'other process screenshot')
            self.assertFalse(QImage(str(path)).isNull())


if __name__=='__main__':unittest.main()
