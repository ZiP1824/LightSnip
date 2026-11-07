import unittest
from ocr_layout import format_ocr_result,sentence_lines


def box(text,x=0,y=0,width=500,height=20):
    return [[[x,y],[x+width,y],[x+width,y+height],[x,y+height]],text,.99]


class LayoutChecks(unittest.TestCase):
    def test_reflows_chinese_wraps_and_keeps_paragraph_gap(self):
        result=[box('建议在原生 Windows 上安装 Git for',y=0),
                box('Windows，以便使用 Bash 工具。如果还未安装，',y=30),
                box('请先完成安装。',y=60),
                box('第二段开始。继续说明！',y=110)]
        self.assertEqual(format_ocr_result(result),'建议在原生 Windows 上安装 Git for Windows，以便使用 Bash 工具。\n如果还未安装，请先完成安装。\n\n第二段开始。\n继续说明！')

    def test_english_sentences_urls_versions_and_abbreviations(self):
        text='Dr. Li uses v3.14 on Windows. Visit https://example.com/docs?q=1. Done!'
        self.assertEqual(sentence_lines(text),'Dr. Li uses v3.14 on Windows.\nVisit https://example.com/docs?q=1.\nDone!')
        self.assertEqual(sentence_lines('Use U.S. tools. Next.'),'Use U.S. tools.\nNext.')

    def test_quoted_dialogue_keeps_closing_quotes(self):
        self.assertEqual(sentence_lines('甲：“你好！”乙：“再见。”'),'甲：“你好！”\n乙：“再见。”')

    def test_same_row_fragments_retain_word_spaces(self):
        self.assertEqual(format_ocr_result([box('Hello',x=0,width=55),box('world.',x=70,width=70)]),'Hello world.')

    def test_indented_paragraph_is_not_joined_to_previous_line(self):
        self.assertEqual(format_ocr_result([box('上一段结束。'),box('新段文字',x=40,y=30),box('继续本段。',y=60)]),'上一段结束。\n\n新段文字继续本段。')

    def test_two_paragraphs_with_only_one_gap(self):
        self.assertEqual(format_ocr_result([box('第一段。'),box('第二段。',y=80)]),'第一段。\n\n第二段。')

    def test_numbered_items_remain_separate(self):
        self.assertEqual(format_ocr_result([box('1. Install Git',y=0),box('2. Open Bash',y=30)]),'1. Install Git\n2. Open Bash')

    def test_empty_and_shuffled_lines(self):
        self.assertEqual(format_ocr_result([]),'')
        self.assertEqual(format_ocr_result([box('继续。',y=30),box('开头',y=0)]),'开头继续。')


if __name__=='__main__':unittest.main()
