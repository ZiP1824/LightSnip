# LightSnip — Free, open-source Windows screenshot tool

[中文说明](README.md) · [Download Windows portable release](https://github.com/ZiP1824/LightSnip/releases/latest)

LightSnip is a no-account Windows screenshot application with delayed capture, scrolling capture, local OCR, annotations, pinned images, mosaic brush, screenshot translation, custom hotkeys, multi-monitor capture and silent MP4 recording.

## Features

- Region capture with move and resize controls; automatic window, control and text-region detection.
- Delayed screenshots: configurable 1–60 second countdown for menus and popups; a compact, translucent centered card with shadow and directional easing to avoid the pointer. It does not steal focus and allows clicks through.
- Scrolling screenshots inside a selected region, with vertical/horizontal stitching and live preview.
- Local OCR with an image preview and editable recognized text.
- Shapes, multiple arrow styles, freehand drawing, highlighter, text and numbered markers.
- Rectangle and freehand mosaic tools, with separate brush diameter and pixel-block controls.
- Always-on-top pinned screenshots; drag, zoom, flip and adjust opacity.
- Online text translation using MyMemory, displayed near the original selection.
- Configurable global hotkeys, startup option and remembered save directory.

Press **Ctrl+Shift+1** to capture; **Enter / Ctrl+C** copies and closes; **L** starts scrolling capture; **Shift+C** runs OCR; **Ctrl+T** pins the image. Direct clipboard capture does not create screenshot-history files.

**Ctrl+Shift+4** starts delayed capture by default. Set the delay in Configuration → Capture and customize its hotkey under Hotkeys/Actions. Existing saved bindings are preserved. Start the countdown before opening the menu or popup; pressing the same hotkey again cancels it.

Text annotations can be reopened from the text toolbar. Select a numbered marker and press Delete or use the toolbar button. New markers reuse the lowest missing number. Import and export settings under Configuration → System.

## Install

Download the ZIP from [Releases](https://github.com/ZiP1824/LightSnip/releases/latest), extract the entire `LightSnip` directory and run `LightSnip.exe`. Keep `_internal` and `ThirdPartyLicenses` next to the executable. Python is not required for the portable build.

## Privacy and limitations

OCR runs locally. Translation requires a network connection and sends recognized text, rather than the screenshot image, to MyMemory. The service has an anonymous free quota and may be unavailable on some networks. Version 0.27 does not include offline translation models.

Capture is per display; merged cross-display selection, audio recording, GIF export, in-image translation replacement and automatic updates are not implemented. Detection and scrolling-stitching reliability depend on application accessibility, page layout, overlap and dynamic content.

## Develop

Windows x64 and Python 3.13:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe app.py
.\build.ps1
```

See the Chinese README for the full test command and feature guide.

## License

Project code: [MIT](LICENSE). Dependencies and icons retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).

Developer: **ZiP1824** — zhangxh1994@gmail.com.
