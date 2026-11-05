<#
.SYNOPSIS
    Install the lab software on Windows 10/11.

.DESCRIPTION
    Sets up everything to run the lab instruments from this computer:
    Thorlabs DC2200 and PM400, CoolLED pE-300 and the FLIR Blackfly S camera.
    (The Canon EOS R10 is not supported on Windows: its USB library, libgphoto2,
    exists only for Linux and macOS.)

    Steps:
      1. Python              3.10-3.12; installed with winget if there is none
      2. Python environment  LAB\lab
      3. Python packages     equipment and line-analysis
      4. NI-VISA             checks the VISA library the Thorlabs software installs
      5. Spinnaker / PySpin  installs PySpin from the wheel in Downloads (FLIR camera)
      6. LAB terminal        a desktop shortcut that opens a terminal ready to work
      7. Check               equipment doctor

    Before running it, install the manufacturer software (see README.md here):
    the Thorlabs DC2200 software and Optical Power Monitor, and the Spinnaker SDK.

    No administrator rights are needed. Running it again is safe: finished steps
    are skipped, missing ones are done.

.PARAMETER Python
    Use this Python version (e.g. 3.11) instead of choosing one automatically.

.PARAMETER SpinnakerWheel
    Path of the Spinnaker Python wheel (spinnaker_python-...-win_amd64.whl, or the
    zip file it comes in), if it is not in Downloads.

.PARAMETER PythonOnly
    Only make or update the Python environment (steps 1-3 and 7).

.PARAMETER NoShortcut
    Do not put the "LAB terminal" shortcut on the desktop.

.EXAMPLE
    PS> .\install.bat
    Everything, with the Python version that matches the Spinnaker wheel.

.EXAMPLE
    PS> .\install.bat -Python 3.11 -SpinnakerWheel C:\Temp\spinnaker_python-4.2.0.83-cp311-cp311-win_amd64.zip

.NOTES
    Documentation: packaging\windows\README.md and INSTALL.md in LAB.
    Written for Windows PowerShell 5.1 (built into Windows) and PowerShell 7.
#>
param(
    [string]$Python = "",
    [string]$SpinnakerWheel = "",
    [switch]$PythonOnly,
    [switch]$NoShortcut
)
$ErrorActionPreference = "Stop"

# =============================================================================
# Settings
# =============================================================================
$PythonVersions = @("3.12", "3.11", "3.10")     # PySpin wheels exist for these; preferred first
$Extras = "thorlabs,coolled,flir"               # no "canon" on Windows

# =============================================================================
# Output
# =============================================================================
$script:Step = 0
$script:Steps = 7
function Write-Step($text) {
    $script:Step++
    Write-Host ""
    Write-Host ("== {0}/{1}  {2}" -f $script:Step, $script:Steps, $text) -ForegroundColor Cyan
}
function Write-Note($text) { Write-Host "   $text" }
function Write-Ok($text)   { Write-Host "   $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "   ! $text" -ForegroundColor Yellow }

# =============================================================================
# Running other programs
#   With $ErrorActionPreference = "Stop", Windows PowerShell 5.1 turns anything a
#   program writes to stderr into an error when stderr is redirected. These two
#   helpers run a program quietly with "Continue" instead.
# =============================================================================
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
# Invoke-Checked: run a program, show its output (Out-Host keeps it out of the
# function's return value) and stop with an error if it fails.
function Invoke-Checked([string]$exe, [string[]]$argList, [string]$what) {
    & $exe @argList | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

# =============================================================================
# Paths
#   $Equipment  the equipment folder;  $Lab  the LAB folder ("" if used alone)
#   $Venv       the Python environment: LAB\lab, or equipment\.venv
# =============================================================================
$Equipment = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Lab = Split-Path $Equipment -Parent
if (Test-Path (Join-Path $Lab "line-analysis")) {
    $Venv = Join-Path $Lab "lab"
} else {
    $Lab = ""
    $Venv = Join-Path $Equipment ".venv"
}
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$WorkDir = if ($Lab) { $Lab } else { $Equipment }

# =============================================================================
# Spinnaker wheel and Python version
# =============================================================================

# Find-SpinnakerWheel: the newest spinnaker_python-*.whl (or the .zip it comes in)
# in Downloads, this folder, or the Spinnaker install folder; "" if none.
function Find-SpinnakerWheel {
    if ($SpinnakerWheel) {
        $given = (Resolve-Path $SpinnakerWheel).Path
        if ($given -like "*.zip") { return (Expand-SpinnakerZip $given) }
        return $given
    }
    $places = @((Join-Path $env:USERPROFILE "Downloads"), $PSScriptRoot,
                "C:\Program Files\Teledyne\Spinnaker", "C:\Program Files\FLIR Systems\Spinnaker")
    foreach ($place in $places) {
        if (-not (Test-Path $place)) { continue }
        $whl = Get-ChildItem -Path $place -Recurse -Depth 3 -Filter "spinnaker_python-*win_amd64.whl" `
               -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($whl) { return $whl.FullName }
        $zip = Get-ChildItem -Path $place -Recurse -Depth 2 -Filter "spinnaker_python-*win_amd64*.zip" `
               -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($zip) { return (Expand-SpinnakerZip $zip.FullName) }
    }
    return ""
}

function Expand-SpinnakerZip([string]$zipPath) {
    $dest = Join-Path $env:TEMP ("spinnaker_" + [IO.Path]::GetFileNameWithoutExtension($zipPath))
    Expand-Archive -Path $zipPath -DestinationPath $dest -Force
    $whl = Get-ChildItem -Path $dest -Recurse -Filter "spinnaker_python-*win_amd64.whl" | Select-Object -First 1
    if ($whl) { return $whl.FullName }
    return ""
}

# Get-WheelPythonVersion: "spinnaker_python-4.2-cp312-...whl" -> "3.12"
function Get-WheelPythonVersion([string]$wheel) {
    if ($wheel -match "-cp3(\d+)-") { return "3." + $Matches[1] }
    return ""
}

# Find-Python: the python.exe of a version: the py launcher first, then the usual folders
function Find-Python([string]$version) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $found = Get-NativeOutput "py" @("-$version", "-c", "import sys; print(sys.executable)")
        if ($found) { return $found }
    }
    $short = $version.Replace(".", "")
    foreach ($candidate in @("$env:LOCALAPPDATA\Programs\Python\Python$short\python.exe",
                             "C:\Program Files\Python$short\python.exe")) {
        if (Test-Path $candidate) { return $candidate }
    }
    return ""
}

# =============================================================================
# Steps
# =============================================================================

# 1. Python: the version of the Spinnaker wheel, else 3.12 / 3.11 / 3.10; winget if none
function Install-Python([string]$wheel) {
    $versions = $PythonVersions
    if ($Python) {
        $versions = @($Python)
    } elseif ($wheel) {
        $wheelVersion = Get-WheelPythonVersion $wheel
        if ($wheelVersion) {
            $versions = @($wheelVersion)
            Write-Note "Spinnaker wheel for Python ${wheelVersion}: $wheel"
        }
    }
    foreach ($version in $versions) {
        $exe = Find-Python $version
        if ($exe) { Write-Ok "using $exe"; return $exe }
    }
    $version = $versions[0]
    Write-Note "Python $version not found: installing it with winget"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is not available. Install Python $version from python.org (tick 'Add python.exe to PATH'), then run this again."
    }
    Invoke-Checked "winget" @("install", "-e", "--id", "Python.Python.$version", "--scope", "user",
                              "--accept-package-agreements", "--accept-source-agreements") "winget"
    $exe = Find-Python $version
    if (-not $exe) { throw "Python $version was installed but not found; open a new terminal and run this again." }
    Write-Ok "installed and using $exe"
    return $exe
}

# 2. Python environment
function New-LabEnvironment([string]$pythonExe) {
    if (Test-Path $VenvPython) {
        Write-Note "using the existing $Venv"
        return
    }
    Invoke-Checked $pythonExe @("-m", "venv", $Venv) "creating the environment $Venv"
    Write-Ok "created $Venv"
}

# 3. Python packages
function Install-LabPackages {
    Invoke-Checked $VenvPython @("-m", "pip", "install", "--upgrade", "pip") "pip upgrade"
    $equipmentSpec = '{0}[{1}]' -f $Equipment, $Extras
    if ($Lab) {
        $analysisSpec = '{0}[test]' -f (Join-Path $Lab "line-analysis")
        Invoke-Checked $VenvPython @("-m", "pip", "install", "-e", $equipmentSpec, "-e", $analysisSpec) "pip install"
        New-Item -ItemType Directory -Force -Path (Join-Path $Lab "data\input"), (Join-Path $Lab "data\output") | Out-Null
        Write-Ok "installed equipment [$Extras] and line-analysis"
    } else {
        Invoke-Checked $VenvPython @("-m", "pip", "install", "-e", $equipmentSpec) "pip install"
        Write-Ok "installed equipment [$Extras]"
    }
}

# 4. NI-VISA (DC2200, PM400): comes with the Thorlabs software; cannot be installed here
function Test-Visa {
    $visa = @("$env:SystemRoot\System32\visa64.dll", "$env:SystemRoot\System32\visa32.dll") |
            Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($visa) {
        Write-Ok "VISA library found: $visa"
    } else {
        Write-Warn "no VISA library found. Install the Thorlabs software, which brings NI-VISA:"
        Write-Warn "  DC2200: thorlabs.com > DC2200 > Software;  PM400: 'Optical Power Monitor'"
        Write-Warn "  (or NI-VISA from ni.com). Then run this installer again."
    }
    Write-Note "PM400: in Thorlabs' 'Power Meter Driver Switcher' the PM400 must use the"
    Write-Note "'TLPM (VISA)' driver, or VISA cannot see it."
}

# 5. Spinnaker / PySpin (FLIR camera): from the wheel the user downloaded
function Install-PySpin([string]$wheel) {
    if (Test-Native $VenvPython @("-c", "import PySpin")) {
        Write-Ok "PySpin is already installed"
        return
    }
    $envVersion = Get-NativeOutput $VenvPython @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")
    if (-not $wheel) {
        Write-Warn "PySpin is not installed. From teledynevisionsolutions.com (free account), download:"
        Write-Warn "  1. the Spinnaker SDK for Windows 64-bit, and install it (it brings the camera driver)"
        Write-Warn "  2. the Spinnaker Python package for Windows, Python $envVersion (cp$($envVersion.Replace('.', '')))"
        Write-Warn "Leave the .zip or .whl in Downloads and run this installer again."
        return
    }
    $wheelVersion = Get-WheelPythonVersion $wheel
    if ($wheelVersion -and $wheelVersion -ne $envVersion) {
        Write-Warn "the Spinnaker wheel is for Python $wheelVersion, the environment has Python $envVersion."
        Write-Warn "Delete $Venv and run:  install.bat -Python $wheelVersion"
        return
    }
    Invoke-Checked $VenvPython @("-m", "pip", "install", $wheel) "installing PySpin"
    Write-Ok "PySpin installed from $wheel"
}

# 6. LAB terminal: lab-terminal.cmd and a desktop shortcut to it
function New-LabTerminal {
    $shellCmd = Join-Path $WorkDir "lab-terminal.cmd"
    $activate = Join-Path $Venv "Scripts\activate.bat"
    @"
@echo off
rem Opens a terminal with the lab environment active (made by install.ps1)
call "$activate"
cd /d "$WorkDir"
echo Ready: 'equipment' and 'analysis' are available in this terminal.
cmd /k
"@ | Set-Content -Path $shellCmd -Encoding ASCII
    Write-Ok "made $shellCmd"
    if ($NoShortcut) { return }
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $shell = New-Object -ComObject WScript.Shell
        $link = $shell.CreateShortcut((Join-Path $desktop "LAB terminal.lnk"))
        $link.TargetPath = $shellCmd
        $link.WorkingDirectory = $WorkDir
        $link.Save()
        Write-Ok "desktop shortcut 'LAB terminal'"
    } catch {
        Write-Warn "could not make the desktop shortcut: $_"
    }
}

# 7. Check
function Invoke-Doctor {
    & (Join-Path $Venv "Scripts\equipment.exe") doctor
}

# =============================================================================
# Main
# =============================================================================
if ($PythonOnly) { $script:Steps = 4 }
$wheel = Find-SpinnakerWheel

Write-Step "Python";                         $pythonExe = Install-Python $wheel
Write-Step "Python environment: $Venv";      New-LabEnvironment $pythonExe
Write-Step "Python packages";                Install-LabPackages
if (-not $PythonOnly) {
    Write-Step "NI-VISA (DC2200, PM400)";    Test-Visa
    Write-Step "Spinnaker / PySpin (FLIR)";  Install-PySpin $wheel
    Write-Step "LAB terminal";               New-LabTerminal
}
Write-Step "Check (equipment doctor)";       Invoke-Doctor

Write-Host ""
Write-Host "== Done" -ForegroundColor Cyan
Write-Note "Open 'LAB terminal' on the desktop (or $(Join-Path $WorkDir 'lab-terminal.cmd'))."
Write-Note "pE-300: Windows 10/11 has its USB serial driver built in (a COM port)."
Write-Note "Canon EOS R10: not supported on Windows; use it on Fedora, Ubuntu or macOS."
Write-Note "Check at any time with:  equipment doctor"
