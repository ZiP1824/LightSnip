param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $OutputDirectory) {
    $version = (Get-Content VERSION -Raw).Trim()
    $OutputDirectory = "releases/v$version"
}
& .\.venv\Scripts\python.exe -c "import comtypes.client; comtypes.client.GetModule('UIAutomationCore.dll')"
if ($LASTEXITCODE -ne 0) { throw '控件识别接口生成失败' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --windowed --onedir --distpath $OutputDirectory --name LightSnip --icon assets/icon.ico --add-data 'assets;assets' --hidden-import comtypes.gen.UIAutomationClient --collect-all rapidocr_onnxruntime --collect-all onnxruntime --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineQuick --exclude-module PySide6.QtPdf --exclude-module PySide6.QtPdfWidgets app.py
if ($LASTEXITCODE -ne 0) { throw '打包失败' }
# Qt uses the Windows ICU system API. A different ICU on PATH can be collected
# by the packager and shadow the system DLL despite exporting different symbols.
$bundleRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "$OutputDirectory\LightSnip"))
foreach ($runtimeName in @('icuuc.dll','icudt78.dll')) {
    $runtimePath = [IO.Path]::GetFullPath((Join-Path $bundleRoot "_internal\$runtimeName"))
    if (-not $runtimePath.StartsWith($bundleRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '打包路径检查失败' }
    if (Test-Path -LiteralPath $runtimePath) { Remove-Item -LiteralPath $runtimePath }
}
Copy-Item -LiteralPath README.md -Destination (Join-Path $bundleRoot '使用说明.md')
Copy-Item -LiteralPath LICENSE -Destination (Join-Path $bundleRoot 'LICENSE')
& .\.venv\Scripts\python.exe collect_licenses.py $bundleRoot
