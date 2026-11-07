# Third-party notices

The MIT license in this repository applies to LightSnip project code. It does not replace the licenses of bundled dependencies, their models or icons.

| Component | Role | Upstream |
| --- | --- | --- |
| PySide6 / Qt / shiboken6 | Windows UI | https://doc.qt.io/qtforpython-6/licenses.html |
| RapidOCR | Local OCR pipeline and packaged OCR models | https://github.com/RapidAI/RapidOCR |
| ONNX Runtime | Local OCR model inference | https://github.com/microsoft/onnxruntime |
| OpenCV / NumPy / Pillow | Image processing | https://opencv.org/ · https://numpy.org/ · https://python-pillow.github.io/ |
| comtypes | Windows UI Automation interfaces | https://github.com/enthought/comtypes |
| Lucide and its Feather-derived icons | Toolbar and settings icons | https://lucide.dev/license |

Lucide's original license is retained in `assets/lucide/LICENSE`. Some functional SVGs in the same directory are drawn by the LightSnip project. The application icon is a generated project asset.

`collect_licenses.py` copies installed dependency license, copying and notice files into the portable build's `ThirdPartyLicenses` directory, with package versions recorded in `INDEX.txt`. Include this directory when redistributing a portable build. Consult each upstream project's license and source for its complete terms and notices.

MyMemory is an external online translation service, not a bundled translation engine. Its service terms and quotas are separate from LightSnip's source license: https://mymemory.translated.net/doc/spec.php.
