import unittest
import cv2
import numpy as np
from scroll_stitcher import ContentStitcher,estimate_shift
from capture_tools import stitch_shift


class ScrollChecks(unittest.TestCase):
    def setUp(self):
        self.document=np.random.default_rng(37).integers(0,256,(2600,400,3),dtype=np.uint8)

    def frame(self,offset,chrome=False):
        frame=self.document[offset:offset+500].copy()
        if chrome:
            frame[:40]=(45,70,90)
            frame[-50:]=(200,50,30)
        frame[378:438,326:386]=(5,240,15)
        return frame

    @staticmethod
    def button_count(image):
        mask=np.all(image==np.array([5,240,15],np.uint8),axis=2).astype(np.uint8)
        count,_,stats,_=cv2.connectedComponentsWithStats(mask)
        return sum(stats[index,cv2.CC_STAT_AREA]>80 for index in range(1,count))

    def test_fixed_button_is_recovered_without_repetition(self):
        frames=[self.frame(offset) for offset in [0,100,200,300,400]]
        # Reproduce the old tail-only compositor's duplicated button.
        old=np.concatenate([frames[0]]+[frame[-100:] for frame in frames[1:]])
        self.assertGreater(self.button_count(old),1)
        stitcher=ContentStitcher(frames[0])
        for frame in frames[1:]:self.assertEqual(stitcher.append(frame),100)
        self.assertEqual(stitcher.image().shape,(900,400,3))
        self.assertLessEqual(self.button_count(stitcher.image()),1)
        self.assertTrue(np.array_equal(stitcher.image()[stitcher.valid],self.document[:900][stitcher.valid]))
        # Original screen-position icon is replaced with observed page pixels.
        self.assertTrue(np.array_equal(stitcher.image()[378:438,326:386],self.document[378:438,326:386]))

    def test_fixed_header_footer_appear_only_at_ends(self):
        stitcher=ContentStitcher(self.frame(0,True))
        for offset in [100,200,300,400]:
            self.assertEqual(stitcher.append(self.frame(offset,True)),100)
        result=stitcher.image()
        self.assertTrue(np.all(result[:40]==[45,70,90]))
        self.assertTrue(np.all(result[-50:]==[200,50,30]))
        footer_rows=np.all(result==[200,50,30],axis=(1,2))
        self.assertEqual(int(footer_rows.sum()),50)
        header_rows=np.all(result==[45,70,90],axis=(1,2))
        self.assertEqual(int(header_rows.sum()),40)
        self.assertLessEqual(self.button_count(result),1)
        self.assertLess(int(np.all(result[40:-50]==[200,50,30],axis=2).sum()),10)

    def test_no_motion_unrelated_or_reverse_frames_do_not_grow(self):
        first=self.document[100:600]
        stitcher=ContentStitcher(first)
        self.assertEqual(stitcher.append(first.copy()),0)
        self.assertIsNone(stitcher.append(self.document[1200:1700]))
        self.assertIsNone(stitcher.append(self.document[:500]))
        self.assertEqual(stitcher.image().shape,first.shape)

    def test_plain_document_and_horizontal_orientation(self):
        stitcher=ContentStitcher(self.document[:500])
        self.assertEqual(stitcher.append(self.document[90:590]),90)
        self.assertTrue(np.array_equal(stitcher.image(),self.document[:590]))
        horizontal=self.document.transpose(1,0,2)
        stitcher=ContentStitcher(horizontal[:,:500].transpose(1,0,2))
        self.assertEqual(stitcher.append(horizontal[:,90:590].transpose(1,0,2)),90)
        self.assertTrue(np.array_equal(stitcher.image().transpose(1,0,2),horizontal[:,:590]))

    def test_length_limit_keeps_previous_result(self):
        stitcher=ContentStitcher(self.document[:500],max_length=550)
        with self.assertRaises(OverflowError):stitcher.append(self.document[100:600])
        self.assertEqual(stitcher.image().shape[0],500)

    def test_full_resolution_refinement_after_downsampling(self):
        content=np.random.default_rng(17).integers(0,256,(1500,900,3),dtype=np.uint8)
        a,b=content[:1000].copy(),content[103:1103].copy()
        for frame in [a,b]:
            frame[:80]=(45,70,90)
            frame[-90:]=(200,50,30)
        self.assertEqual(estimate_shift(a,b),103)

    def test_later_clean_frame_replaces_a_transient_tail_artifact(self):
        stitcher=ContentStitcher(self.document[:500])
        temporary=self.document[100:600].copy()
        temporary[470:490,50:90]=(200,50,30)
        self.assertEqual(stitcher.append(temporary),100)
        self.assertEqual(stitcher.append(self.document[200:700]),100)
        self.assertTrue(np.array_equal(stitcher.image(),self.document[:700]))

    def test_white_text_page_with_floating_circle(self):
        paper=np.full((2600,400,3),248,np.uint8)
        for n in range(42):
            y=n*60+35
            cv2.putText(paper,f'Row {n:02d}: document content',(12,y),cv2.FONT_HERSHEY_SIMPLEX,.55,(45,45,45),1,cv2.LINE_AA)
            cv2.rectangle(paper,(12,y+8),(35+n*6,y+15),(n*5%220,80,130),-1)
        def frame(offset):
            value=paper[offset:offset+500].copy()
            cv2.circle(value,(360,426),24,(5,240,15),-1)
            cv2.arrowedLine(value,(360,438),(360,414),(20,20,20),2)
            return value
        stitcher=ContentStitcher(frame(0))
        for offset in [80,160,240,320]:self.assertEqual(stitcher.append(frame(offset)),80)
        self.assertLessEqual(self.button_count(stitcher.image()),1)
        self.assertTrue(np.array_equal(stitcher.image()[400:450,340:380],paper[400:450,340:380]))


if __name__=='__main__':unittest.main()
