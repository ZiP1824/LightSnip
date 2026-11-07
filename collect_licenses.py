"""Preserve dependency license texts in the redistributable folder."""
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys

root=(Path(sys.argv[1]) if len(sys.argv)>1 else Path('dist/LightSnip'))/'ThirdPartyLicenses'
root.mkdir(parents=True,exist_ok=True)
packages=['PySide6','PySide6_Essentials','shiboken6','rapidocr_onnxruntime','onnxruntime',
          'opencv-python','numpy','Pillow','PyYAML','Shapely','pyclipper','six','protobuf','flatbuffers','comtypes']
info=[]
for name in packages:
    dist=distribution(name)
    info.append(f'{name} {dist.version}\nProject: {dist.metadata.get("Home-page", "")}\nLicense: {dist.metadata.get("License-Expression", dist.metadata.get("License", "See bundled license files"))}\n')
    for entry in dist.files or []:
        if any(token in str(entry).lower() for token in ['license','copying','notice']):
            source=Path(dist.locate_file(entry))
            if source.is_file():
                target=root/name/str(entry).replace('../','').replace('..\\','')
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,target)
(root/'INDEX.txt').write_text('\n'.join(info),encoding='utf-8')
