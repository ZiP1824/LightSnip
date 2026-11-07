"""Reflow OCR visual lines using their geometry and existing punctuation."""
import re
from statistics import median

_BULLET = re.compile(r'^(?:[•●▪◆·\-]|\d+[.、)）]|[（(]\d+[）)]|[一二三四五六七八九十]+[、.])\s*')
_CLOSERS = '”’」』）》】〕〉"\''
_ABBREVIATIONS = {'mr','mrs','ms','dr','prof','sr','jr','st','vs','etc','e.g','i.e','fig','no'}


def join_wrapped(left,right):
    if not left:return right
    if not right:return left
    # English words on separate display lines need a word separator; Chinese
    # display wraps do not. Existing spaces inside each OCR line are retained.
    if left[-1].isascii() and right[0].isascii() and left[-1].isalnum() and right[0].isalnum():
        return left+' '+right
    if left[-1] in ',;:!?.' and right[0].isascii() and right[0].isalnum():
        return left+' '+right
    return left+right


def sentence_lines(text):
    """Break at sentence punctuation, preserving decimals, links and quotes."""
    lines=[]
    start=0
    index=0
    while index<len(text):
        char=text[index]
        boundary=char in '。！？!?；;'
        if char=='.':
            previous=text[index-1] if index else ''
            following=text[index+1] if index+1<len(text) else ''
            token=re.search(r'[^\s，。！？；;]+$',text[start:index+1])
            token=token.group() if token else ''
            word=re.search(r'([A-Za-z.]+)\.$',token)
            abbreviation=word and (word.group(1).lower() in _ABBREVIATIONS or re.fullmatch(r'(?:[A-Za-z]\.)+[A-Za-z]?',word.group(1)))
            line_prefix=text[:index+1].rsplit('\n',1)[-1].strip()
            list_number=bool(re.fullmatch(r'\d+\.',line_prefix)) and following.isspace()
            # A dot embedded in a word/number is not a sentence ending.
            boundary=not (previous.isdigit() and following.isdigit() or following.isascii() and following.isalnum() or abbreviation or list_number)
        if boundary:
            end=index+1
            while end<len(text) and text[end] in '。！？!?；;.'+_CLOSERS:end+=1
            # Keep punctuation that belongs to an URL query intact.
            token=text[start:end].rsplit(' ',1)[-1]
            if char in '?!;' and ('://' in token or token.startswith('www.')) and end<len(text) and not text[end].isspace():
                index+=1
                continue
            segment=text[start:end].strip()
            if segment:lines.append(segment)
            start=end
            index=end
        else:index+=1
    tail=text[start:].strip()
    if tail:lines.append(tail)
    return '\n'.join(lines)


def format_ocr_result(result):
    boxes=[]
    for record in result or []:
        points,text=record[0],str(record[1]).strip()
        if not text:continue
        xs=[float(point[0]) for point in points]
        ys=[float(point[1]) for point in points]
        boxes.append(dict(left=min(xs),right=max(xs),top=min(ys),bottom=max(ys),text=text))
    if not boxes:return ''
    height=median(max(1,box['bottom']-box['top']) for box in boxes)
    rows=[]
    for box in sorted(boxes,key=lambda b:((b['top']+b['bottom'])/2,b['left'])):
        center=(box['top']+box['bottom'])/2
        if rows and abs(center-rows[-1]['center'])<=height*.45:
            row=rows[-1]
            row['parts'].append(box)
            row['top']=min(row['top'],box['top'])
            row['bottom']=max(row['bottom'],box['bottom'])
        else:rows.append(dict(parts=[box],top=box['top'],bottom=box['bottom'],center=center))
    for row in rows:
        parts=sorted(row['parts'],key=lambda b:b['left'])
        text=parts[0]['text']
        for previous,current in zip(parts,parts[1:]):
            # Same-line fragments with a visible gap retain a word separator.
            gap=current['left']-previous['right']
            text=(text+' '+current['text']) if gap>height*.25 else join_wrapped(text,current['text'])
        row['text']=text
        row['left']=parts[0]['left']
        row['right']=parts[-1]['right']
    gaps=[max(0,b['top']-a['bottom']) for a,b in zip(rows,rows[1:])]
    # Use the denser half so paragraph gaps cannot become the normal line gap.
    normal_gap=min(height*.55,median(sorted(gaps)[:max(1,(len(gaps)+1)//2)])) if gaps else 0
    base_left=min(row['left'] for row in rows)
    paragraphs=[]
    current=rows[0]['text']
    for previous,row in zip(rows,rows[1:]):
        gap=max(0,row['top']-previous['bottom'])
        paragraph_gap=gap>max(height*.75,normal_gap+height*.55)
        indentation=row['left']-base_left>=height*1.3 and row['left']-previous['left']>=height
        heading=previous['bottom']-previous['top']>height*1.3
        list_row=bool(_BULLET.match(row['text']) or _BULLET.match(previous['text']))
        if paragraph_gap or indentation or heading:
            paragraphs.append(sentence_lines(current))
            current=row['text']
        elif list_row:
            current+='\n'+row['text']
        else:current=join_wrapped(current,row['text'])
    paragraphs.append(sentence_lines(current))
    return '\n\n'.join(paragraphs)
