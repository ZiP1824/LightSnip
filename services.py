"""Local OCR and explicitly requested anonymous translation."""
import html
import re
import urllib.parse
import urllib.request
import json
import threading


def split_utf8(text, limit=480):
    chunks, current, size = [], [], 0
    for char in text:
        n = len(char.encode('utf-8'))
        if size + n > limit:
            chunks.append(''.join(current))
            current, size = [], 0
        current.append(char)
        size += n
    if current:
        chunks.append(''.join(current))
    return chunks


def source_language(text):
    if re.search(r'[\u3040-\u30ff]', text):
        return 'ja'
    if re.search(r'[\uac00-\ud7af]', text):
        return 'ko'
    return 'zh-CN' if re.search(r'[\u4e00-\u9fff]', text) else 'en'


def translate(text, source='auto', target='zh-CN', opener=None):
    if not text.strip():
        raise ValueError('请先识别或输入文字。')
    if len(text) > 5000:
        raise ValueError('每次最多翻译 5,000 字符，请缩短文字。')
    source = source_language(text) if source == 'auto' else source
    if source == target:
        return text
    results = []
    for chunk in split_utf8(text):
        query = urllib.parse.urlencode({'q': chunk, 'langpair': f'{source}|{target}'})
        request = urllib.request.Request('https://api.mymemory.translated.net/get?' + query,
                                        headers={'User-Agent': 'LightSnip/0.1'})
        with (opener or urllib.request.urlopen)(request, timeout=20) as response:
            data = json.load(response)
        if int(data.get('responseStatus', 500)) != 200 or data.get('quotaFinished'):
            raise RuntimeError('翻译服务拒绝请求或免费额度已用完：' + str(data.get('responseDetails', '请稍后重试')))
        result = data.get('responseData', {}).get('translatedText')
        if not isinstance(result, str):
            raise RuntimeError('翻译服务返回了无法识别的结果。')
        results.append(html.unescape(result))
    return ''.join(results)


_ocr = None
_ocr_lock = threading.Lock()


def recognize(png_bytes, *, layout=False):
    global _ocr
    import cv2
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError('无法读取图像。')
    if img.std()<2:return ''
    # Wide crops can contain several lines. The library's default aspect-ratio
    # shortcut treats them as a single text line, often returning no text.
    with _ocr_lock:
        if _ocr is None:
            _ocr = RapidOCR(width_height_ratio=-1,min_height=0)
        background=tuple(int(x) for x in np.median(np.concatenate([img[0],img[-1]]),axis=0))
        padded=cv2.copyMakeBorder(img,18,18,18,18,cv2.BORDER_CONSTANT,value=background)
        result, _ = _ocr(padded)
        if not result:
            enlarged=cv2.resize(padded,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
            result, _ = _ocr(enlarged)
    if layout:
        from ocr_layout import format_ocr_result
        return format_ocr_result(result)
    return '\n'.join(line[1] for line in (result or []))
