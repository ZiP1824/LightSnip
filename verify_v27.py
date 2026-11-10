from pathlib import Path
from types import CodeType
import hashlib
import marshal
from PyInstaller.archive.readers import CArchiveReader

root=Path(__file__).parent
bundle=root/'releases'/('v'+(root/'VERSION').read_text().strip())/'LightSnip'
archive=CArchiveReader(str(bundle/'LightSnip.exe'))
modules=archive.open_embedded_archive('PYZ.pyz')
forbidden=bytes.fromhex('70697870696e').decode()

def strings(code):
    for value in code.co_consts:
        if isinstance(value,str):yield value
        elif isinstance(value,CodeType):yield from strings(value)

for name in ['app','annotation_tools','scroll_capture','settings_ui','services','translation_popup','startup','ocr_layout','scroll_stitcher','file_names','theme','window_detection','element_detection','mosaic']:
    code=marshal.loads(archive.extract(name)) if name=='app' else modules.extract(name)
    values=list(strings(code))
    assert not any(forbidden in value.lower() for value in values),name
    if name in ['app','settings_ui']:
        assert not any('capture/history' in value or '截图历史' in value for value in values),name
    if name in ['app','annotation_tools','settings_ui']:assert 'annotation/arrow_width' in values,name
    if name=='app':
        assert 'OcrDialog' in values
        assert 'capture/window_detection' in values
    if name=='settings_ui':
        assert any('ZiP1824' in value for value in values)
        assert any('zhangxh1994@gmail.com' in value for value in values)
for name in ['icon.png','icon.ico','ui/chevron-down.svg','ui/chevron-up.svg','ui/check-white.svg','lucide/sliders-horizontal.svg','lucide/command.svg','lucide/keyboard.svg','lucide/info.svg']:
    assert hashlib.sha256((root/'assets'/name).read_bytes()).digest()==hashlib.sha256((bundle/'_internal/assets'/name).read_bytes()).digest(),name
print('Packaged theme assets, removed history controls, OCR dialog, developer details and brand checks: PASS')

assert modules.extract('comtypes.gen.UIAutomationClient') is not None
print('Packaged Windows control interfaces: PASS')

for name in modules.toc:
    assert not any(name==removed or name.startswith(removed+".") for removed in ["local_translation","ctranslate2","sentencepiece","verify_translation"]),name
assert not (bundle/"models").exists()
assert not any("ctranslate2" in str(p).lower() or "sentencepiece" in str(p).lower() for p in bundle.rglob("*"))
print("Local translation engine, model files and fallback removed: PASS")

assert modules.extract('delayed_capture') is not None
print('Animated countdown module bundled: PASS')
