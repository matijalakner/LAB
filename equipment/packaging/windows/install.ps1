<#
Install everything the lab equipment needs on Windows 10/11, in one go.

    install.bat                       (double-click, or run in a terminal)
    install.bat -Python 3.11          a specific Python version
    install.bat -SpinnakerWheel C:\path\spinnaker_python-...-cp312-...win_amd64.whl

Run it as your normal user; it does not need administrator rights. It can be run
again at any time; steps that are already done are skipped.

What it does
  1. Python 3.10-3.12 (installed with winget if there is none)
  2. the Python environment (LAB\lab) with equipment and line-analysis
  3. checks NI-VISA for the DC2200 / PM400 (comes with the Thorlabs software)
  4. installs PySpin for the FLIR camera from the Spinnaker wheel you downloaded
  5. a "LAB terminal" shortcut on the desktop, with the environment active
  6. 'equipment doctor' to check the result

Not on Windows: the Canon EOS R10 (its USB library, libgphoto2, is Linux/macOS
only). Everything else works: DC2200, PM400, pE-300, FLIR, the ramps and pairings.
#>
param(
    [string]$Python = "",
    [string]$SpinnakerWheel = "",
    [switch]$NoShortcut
)
$ErrorActionPreference = "Stop"

function Say($text)  { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
# Native programs that may write to stderr: with "Stop", Windows PowerShell 5.1
# would turn that into an error, so these helpers run them with "Continue".
function Test-Native([string]$exe, [string[]]$argList) {
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { & $exe @argList 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) }
    catch { return $false }
    finally { $ErrorActionPreference = $old }
}
function Get-NativeOutput([string]$exe, [string[]]$argList) {
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try {
        $out = & $exe @argList 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return ($out | Select-Object -Last 1).ToString().Trim() }
        return ""
    }
    catch { return "" }
    finally { $ErrorActionPreference = $old }
}
function Note($text) { Write-Host "   $text" }
function Warn($text) { Write-Host "   ! $text" -ForegroundColor Yellow }

$Equipment = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Lab = Split-Path $Equipment -Parent
if (Test-Path (Join-Path $Lab "line-analysis")) {
    $Venv = Join-Path $Lab "lab"                 # the same environment name as on Fedora
} else {
    $Lab = ""
    $Venv = Join-Path $Equipment ".venv"
}

# ---------------------------------------------------------------------------
# Python: 3.10-3.12 (PySpin wheels exist for these); the Spinnaker wheel decides
# ---------------------------------------------------------------------------
function Find-SpinnakerWheel {
    if ($SpinnakerWheel) { return (Resolve-Path $SpinnakerWheel).Path }
    $places = @((Join-Path $env:USERPROFILE "Downloads"), (Join-Path $Equipment "packaging\windows"),
                "C:\Program Files\Teledyne\Spinnaker", "C:\Program Files\FLIR Systems\Spinnaker")
    foreach ($p in $places) {
        if (-not (Test-Path $p)) { continue }
        $whl = Get-ChildItem -Path $p -Recurse -Depth 3 -Filter "spinnaker_python-*win_amd64.whl" `
               -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($whl) { return $whl.FullName }
        $zip = Get-ChildItem -Path $p -Recurse -Depth 2 -Filter "spinnaker_python-*win_amd64*.zip" `
               -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($zip) {
            $dest = Join-Path $env:TEMP ("spinnaker_" + [IO.Path]::GetFileNameWithoutExtension($zip.Name))
            Expand-Archive -Path $zip.FullName -DestinationPath $dest -Force
            $whl = Get-ChildItem -Path $dest -Recurse -Filter "spinnaker_python-*win_amd64.whl" |
                   Select-Object -First 1
            if ($whl) { return $whl.FullName }
        }
    }
    return ""
}

function Wheel-PythonVersion($wheel) {
    if ($wheel -match "-cp3(\d+)-") { return "3." + $Matches[1] }
    return ""
}

function Find-Python($version) {
    # the py launcher first, then the usual install folders
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $found = Get-NativeOutput "py" @("-$version", "-c", "import sys; print(sys.executable)")
        if ($found) { return $found }
    }
    $short = $version.Replace(".", "")
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python$short\python.exe",
                     "C:\Program Files\Python$short\python.exe")) {
        if (Test-Path $p) { return $p }
    }
    return ""
}

$wheel = Find-SpinnakerWheel
Say "1/6  Python"
$versions = @("3.12", "3.11", "3.10")
if ($Python) { $versions = @($Python) }
elseif ($wheel) {
    $v = Wheel-PythonVersion $wheel
    if ($v) { $versions = @($v); Note "Spinnaker wheel found for Python $v : $wheel" }
}
$exe = ""
foreach ($v in $versions) { $exe = Find-Python $v; if ($exe) { break } }
if (-not $exe) {
    $v = $versions[0]
    Note "Python $v not found: installing it with winget"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "winget is not available. Install Python $v from python.org (tick 'Add to PATH'), then run this again."
    }
    & winget install -e --id "Python.Python.$v" --scope user --accept-package-agreements --accept-source-agreements
    $exe = Find-Python $v
    if (-not $exe) { throw "Python $v was installed but not found; open a new terminal and run this again." }
}
Note "using $exe"

# ---------------------------------------------------------------------------
Say "2/6  Python environment: $Venv"
$venvPython = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $exe -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "could not create the environment $Venv" }
}
& $venvPython -m pip install --upgrade pip
$equipmentSpec = '{0}[thorlabs,coolled,flir]' -f $Equipment
if ($Lab) {
    $analysisSpec = '{0}[test]' -f (Join-Path $Lab "line-analysis")
    & $venvPython -m pip install -e $equipmentSpec -e $analysisSpec
    New-Item -ItemType Directory -Force -Path (Join-Path $Lab "data\input"), (Join-Path $Lab "data\output") | Out-Null
} else {
    & $venvPython -m pip install -e $equipmentSpec
}
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# ---------------------------------------------------------------------------
Say "3/6  NI-VISA (Thorlabs DC2200 and PM400)"
$visa = @("$env:SystemRoot\System32\visa64.dll", "$env:SystemRoot\System32\visa32.dll") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
if ($visa) {
    Note "VISA library found: $visa"
} else {
    Warn "no VISA library found. Install the Thorlabs software, which brings NI-VISA:"
    Warn "  DC2200: thorlabs.com > DC2200 > Software;  PM400: 'Optical Power Monitor'"
    Warn "  (or NI-VISA from ni.com). Then run this installer again."
}
Note "PM400: in Thorlabs' 'Power Meter Driver Switcher' the PM400 must use the"
Note "'TLPM (VISA)' driver, not 'TLPMX' / native, or VISA cannot see it."

# ---------------------------------------------------------------------------
Say "4/6  Spinnaker / PySpin (FLIR camera)"
if (Test-Native $venvPython @("-c", "import PySpin")) {
    Note "PySpin is already installed"
} elseif ($wheel) {
    $pyv = Get-NativeOutput $venvPython @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")
    $wv = Wheel-PythonVersion $wheel
    if ($wv -and $wv -ne $pyv) {
        Warn "the Spinnaker wheel is for Python $wv but the environment has Python $pyv."
        Warn "Delete $Venv and run: install.bat -Python $wv"
    } else {
        & $venvPython -m pip install $wheel
        if ($LASTEXITCODE -eq 0) { Note "PySpin installed from $wheel" }
        else { Warn "installing $wheel failed" }
    }
} else {
    $pyv = Get-NativeOutput $venvPython @("-c", "import sys; print('%d%d' % sys.version_info[:2])")
    Warn "PySpin is not installed. From teledynevisionsolutions.com (free account), download:"
    Warn "  1. the Spinnaker SDK for Windows 64-bit, and install it (it brings the camera driver)"
    Warn "  2. the Spinnaker Python package for Windows, Python 3.$($pyv.Substring(1)) (cp$pyv)"
    Warn "Leave the .zip or .whl in Downloads and run this installer again."
}

# ---------------------------------------------------------------------------
Say "5/6  LAB terminal"
$shellDir = $Equipment
if ($Lab) { $shellDir = $Lab }
$shellCmd = Join-Path $shellDir "lab-terminal.cmd"
$activate = Join-Path $Venv "Scripts\activate.bat"
@"
@echo off
rem Opens a terminal with the lab environment active (made by install.ps1)
call "$activate"
cd /d "$shellDir"
echo Ready: 'equipment' and 'analysis' are available in this terminal.
cmd /k
"@ | Set-Content -Path $shellCmd -Encoding ASCII
Note "made $shellCmd"
if (-not $NoShortcut) {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $ws = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut((Join-Path $desktop "LAB terminal.lnk"))
        $lnk.TargetPath = $shellCmd
        $lnk.WorkingDirectory = $shellDir
        $lnk.Save()
        Note "desktop shortcut 'LAB terminal'"
    } catch { Warn "could not make the desktop shortcut: $_" }
}

# ---------------------------------------------------------------------------
Say "6/6  Check (equipment doctor)"
& (Join-Path $Venv "Scripts\equipment.exe") doctor

Say "Done"
Note "Open 'LAB terminal' on the desktop (or $shellCmd) and use 'equipment' / 'analysis'."
Note "pE-300: Windows 10/11 has the USB serial driver built in; it shows up as a COM port."
Note "Canon EOS R10: not supported on Windows (use it on the Fedora computer)."
