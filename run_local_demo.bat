@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "DEFAULT_VENV_DIR=%PROJECT_ROOT%\.venv"
set "DEFAULT_OUTPUT_DIR=%PROJECT_ROOT%\artifacts\live\one-click"
set "DEFAULT_ARTIFACT_PATH=%DEFAULT_OUTPUT_DIR%\live_runtime_result.json"
set "DEFAULT_UI_BIND=127.0.0.1"
set "DEFAULT_UI_PORT=8000"
set "DEFAULT_SOURCE_MODE=mp3"
set "DEFAULT_RUNTIME_MODE=smoke"
set "DEFAULT_MIC_BACKEND=fake"
set "DEFAULT_DEVICE=cpu"

set "VENV_DIR=%DEFAULT_VENV_DIR%"
set "OUTPUT_DIR=%DEFAULT_OUTPUT_DIR%"
set "ARTIFACT_PATH=%DEFAULT_ARTIFACT_PATH%"
set "UI_BIND=%DEFAULT_UI_BIND%"
set "UI_PORT=%DEFAULT_UI_PORT%"
set "SOURCE_MODE=%DEFAULT_SOURCE_MODE%"
set "RUNTIME_MODE=%DEFAULT_RUNTIME_MODE%"
set "MIC_BACKEND=%DEFAULT_MIC_BACKEND%"
set "MIC_DEVICE=default"
set "DEVICE=%DEFAULT_DEVICE%"
set "INPUT_PATH="
set "SKIP_INSTALL=false"
set "INSTALL_ONLY=false"
set "WITH_GPU=false"
set "WITH_MIC=false"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "BASE_PYTHON="
set "BASE_PYTHON_ARGS="
set "BASE_PYTHON_DISPLAY="

call :parse_args %*
if errorlevel 1 exit /b 1

call :validate_args
if errorlevel 1 exit /b 1

call :create_venv_if_needed
if errorlevel 1 exit /b 1

if not exist "%VENV_PYTHON%" (
  call :fail "Virtual environment python not found at %VENV_PYTHON%"
  exit /b 1
)

call :ensure_supported_python "%VENV_PYTHON%" ""
if errorlevel 1 (
  call :fail "Virtual environment python at %VENV_PYTHON% is unsupported. Use Python >=3.10,<3.13."
  exit /b 1
)

if /I not "%SKIP_INSTALL%"=="true" (
  call :install_dependencies
  if errorlevel 1 exit /b 1
) else (
  echo run_local_demo: skipping dependency installation
)

if /I "%INSTALL_ONLY%"=="true" (
  echo run_local_demo: dependencies installed, exiting (--install-only)
  exit /b 0
)

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

echo run_local_demo: running backend artifact generation
if defined INPUT_PATH (
  "%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\live\run_live_separation.py" ^
    --source-mode "%SOURCE_MODE%" ^
    --output-dir "%OUTPUT_DIR%" ^
    --artifact-path "%ARTIFACT_PATH%" ^
    --mode "%RUNTIME_MODE%" ^
    --device-requested "%DEVICE%" ^
    --device-used "%DEVICE%" ^
    --mic-backend "%MIC_BACKEND%" ^
    --mic-device "%MIC_DEVICE%" ^
    --input "%INPUT_PATH%"
) else (
  "%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\live\run_live_separation.py" ^
    --source-mode "%SOURCE_MODE%" ^
    --output-dir "%OUTPUT_DIR%" ^
    --artifact-path "%ARTIFACT_PATH%" ^
    --mode "%RUNTIME_MODE%" ^
    --device-requested "%DEVICE%" ^
    --device-used "%DEVICE%" ^
    --mic-backend "%MIC_BACKEND%" ^
    --mic-device "%MIC_DEVICE%"
)
if errorlevel 1 exit /b 1

"%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\ui\encode_artifact_path.py" "%PROJECT_ROOT%" "%ARTIFACT_PATH%" > "%TEMP%\encode_path_tmp.txt"
if errorlevel 1 (
  del "%TEMP%\encode_path_tmp.txt" >nul 2>&1
  call :fail "Artifact path must stay inside the repository so the UI can serve it."
  exit /b 1
)
set /p ENCODED_ARTIFACT_PATH=<"%TEMP%\encode_path_tmp.txt"
del "%TEMP%\encode_path_tmp.txt" >nul 2>&1

set "UI_URL=http://%UI_BIND%:%UI_PORT%/ui/compare/?artifact=%ENCODED_ARTIFACT_PATH%"
echo run_local_demo: artifact ready at %ARTIFACT_PATH%
echo run_local_demo: starting compare UI at %UI_URL%
echo run_local_demo: press Ctrl+C to stop the server

"%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\ui\serve_compare_demo.py" ^
  --bind "%UI_BIND%" ^
  --port "%UI_PORT%" ^
  --directory "%PROJECT_ROOT%"
exit /b %errorlevel%

:usage
echo Usage: run_local_demo.bat [options]
echo.
echo Creates or reuses .venv, installs project dependencies, runs the live separation CLI
echo to generate a fresh artifact, then starts the compare UI with that artifact preloaded.
echo.
echo Options:
echo   --source-mode ^<mp3^|video-audio^|mic^>  Source used for the backend run. Default: mp3
echo   --input ^<path^>                       Optional input file for mp3 or video-audio mode
echo   --output-dir ^<path^>                  Output directory for generated stems and JSON
echo   --ui-bind ^<host^>                     UI bind address. Default: 127.0.0.1
echo   --ui-port ^<port^>                     UI port. Default: 8000
echo   --mode ^<smoke^|full^>                  Backend runtime mode. Default: smoke
echo   --device ^<cpu^|gpu^>                   Device metadata forwarded to the backend. Default: cpu
echo   --mic-backend ^<fake^|sounddevice^>     Mic backend when --source-mode mic is used. Default: fake
echo   --mic-device ^<name^>                  Mic device identifier. Default: default
echo   --with-gpu                           Install the optional gpu extra
echo   --with-mic                           Install the optional mic extra
echo   --skip-install                       Reuse the current environment without pip install
echo   --install-only                       Install dependencies then exit without running anything
echo   --help                               Show this help text
echo.
echo Examples:
echo   run_local_demo.bat
echo   run_local_demo.bat --source-mode video-audio --mode smoke
echo   run_local_demo.bat --source-mode mic --mic-backend sounddevice --with-mic
echo   run_local_demo.bat --mode full --device gpu --with-gpu
exit /b 0

:parse_args
if "%~1"=="" exit /b 0
if /I "%~1"=="--source-mode" (
  if "%~2"=="" (
    call :fail "Missing value for --source-mode"
    exit /b 1
  )
  set "SOURCE_MODE=%~2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--input" (
  if "%~2"=="" (
    call :fail "Missing value for --input"
    exit /b 1
  )
  set "INPUT_PATH=%~2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--output-dir" (
  if "%~2"=="" (
    call :fail "Missing value for --output-dir"
    exit /b 1
  )
  set "OUTPUT_DIR=%~2"
  set "ARTIFACT_PATH=%OUTPUT_DIR%\live_runtime_result.json"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--ui-bind" (
  if "%~2"=="" (
    call :fail "Missing value for --ui-bind"
    exit /b 1
  )
  set "UI_BIND=%~2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--ui-port" (
  if "%~2"=="" (
    call :fail "Missing value for --ui-port"
    exit /b 1
  )
  set "UI_PORT=%~2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--mode" (
  if "%~2"=="" (
    call :fail "Missing value for --mode"
    exit /b 1
  )
  set "RUNTIME_MODE=%~2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--device" (
  if "%~2"=="" (
    call :fail "Missing value for --device"
    exit /b 1
  )
  set "DEVICE=%~2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--mic-backend" (
  if "%~2"=="" (
    call :fail "Missing value for --mic-backend"
    exit /b 1
  )
  set "MIC_BACKEND=%~2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--mic-device" (
  if "%~2"=="" (
    call :fail "Missing value for --mic-device"
    exit /b 1
  )
  set "MIC_DEVICE=%~2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--with-gpu" (
  set "WITH_GPU=true"
  shift
  goto parse_args
)
if /I "%~1"=="--with-mic" (
  set "WITH_MIC=true"
  shift
  goto parse_args
)
if /I "%~1"=="--skip-install" (
  set "SKIP_INSTALL=true"
  shift
  goto parse_args
)
if /I "%~1"=="--install-only" (
  set "INSTALL_ONLY=true"
  shift
  goto parse_args
)
if /I "%~1"=="--help" (
  call :usage
  exit /b 0
)
if /I "%~1"=="-h" (
  call :usage
  exit /b 0
)
call :fail "Unknown argument: %~1"
exit /b 1

:validate_args
if /I not "%SOURCE_MODE%"=="mp3" if /I not "%SOURCE_MODE%"=="video-audio" if /I not "%SOURCE_MODE%"=="mic" (
  call :fail "--source-mode must be one of: mp3, video-audio, mic"
  exit /b 1
)
if /I not "%RUNTIME_MODE%"=="smoke" if /I not "%RUNTIME_MODE%"=="full" (
  call :fail "--mode must be one of: smoke, full"
  exit /b 1
)
if /I not "%DEVICE%"=="cpu" if /I not "%DEVICE%"=="gpu" (
  call :fail "--device must be one of: cpu, gpu"
  exit /b 1
)
if /I not "%MIC_BACKEND%"=="fake" if /I not "%MIC_BACKEND%"=="sounddevice" (
  call :fail "--mic-backend must be one of: fake, sounddevice"
  exit /b 1
)
if defined INPUT_PATH if /I "%SOURCE_MODE%"=="mic" (
  call :fail "--input cannot be used with --source-mode mic"
  exit /b 1
)
if /I "%SOURCE_MODE%"=="mic" if /I "%MIC_BACKEND%"=="sounddevice" set "WITH_MIC=true"
if /I "%RUNTIME_MODE%"=="full" set "WITH_GPU=true"
if /I "%DEVICE%"=="gpu" set "WITH_GPU=true"
exit /b 0

:create_venv_if_needed
if exist "%VENV_PYTHON%" (
  call :ensure_supported_python "%VENV_PYTHON%" ""
  if not errorlevel 1 (
    echo run_local_demo: reusing virtual environment at %VENV_DIR%
    exit /b 0
  )
)

call :find_python
if errorlevel 1 exit /b 1

if exist "%VENV_PYTHON%" (
  echo run_local_demo: rebuilding virtual environment at %VENV_DIR% with %BASE_PYTHON_DISPLAY%
  call :run_base_python -m venv --clear "%VENV_DIR%"
  exit /b %errorlevel%
)

echo run_local_demo: creating virtual environment at %VENV_DIR% with %BASE_PYTHON_DISPLAY%
call :run_base_python -m venv "%VENV_DIR%"
exit /b %errorlevel%

:find_python
if defined PYTHON_BIN (
  call :ensure_supported_python "%PYTHON_BIN%" ""
  if errorlevel 1 (
    call :fail "PYTHON_BIN points to an unsupported interpreter. Use Python >=3.10,^<3.13."
    exit /b 1
  )
  set "BASE_PYTHON=%PYTHON_BIN%"
  set "BASE_PYTHON_ARGS="
  set "BASE_PYTHON_DISPLAY=%PYTHON_BIN%"
  exit /b 0
)

call :probe_py_launcher 3.12
if not errorlevel 1 exit /b 0
call :probe_py_launcher 3.11
if not errorlevel 1 exit /b 0
call :probe_py_launcher 3.10
if not errorlevel 1 exit /b 0
call :probe_python_command python
if not errorlevel 1 exit /b 0

call :fail "No compatible Python interpreter found on Windows. Install Python 3.10, 3.11, or 3.12 and rerun, or set PYTHON_BIN."
exit /b 1

:probe_py_launcher
where py >nul 2>&1 || exit /b 1
py -%~1 -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info < (3,13) else 1)" >nul 2>&1 || exit /b 1
set "BASE_PYTHON=py"
set "BASE_PYTHON_ARGS=-%~1"
set "BASE_PYTHON_DISPLAY=py -%~1"
exit /b 0

:probe_python_command
where %~1 >nul 2>&1 || exit /b 1
%~1 -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info < (3,13) else 1)" >nul 2>&1 || exit /b 1
set "BASE_PYTHON=%~1"
set "BASE_PYTHON_ARGS="
set "BASE_PYTHON_DISPLAY=%~1"
exit /b 0

:run_base_python
if defined BASE_PYTHON_ARGS (
  "%BASE_PYTHON%" %BASE_PYTHON_ARGS% %*
) else (
  "%BASE_PYTHON%" %*
)
exit /b %errorlevel%

:install_dependencies
set "EXTRAS=dev"
if /I "%WITH_GPU%"=="true" set "EXTRAS=%EXTRAS%,gpu"
if /I "%WITH_MIC%"=="true" set "EXTRAS=%EXTRAS%,mic"
echo run_local_demo: installing project dependencies with extras [%EXTRAS%]
pushd "%PROJECT_ROOT%" >nul || (
  call :fail "Unable to enter project root at %PROJECT_ROOT%"
  exit /b 1
)
"%VENV_PYTHON%" -m pip install -e ".[%EXTRAS%]"
set "INSTALL_EXIT=%errorlevel%"
popd >nul
exit /b %INSTALL_EXIT%

:ensure_supported_python
"%~1" %~2 -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info < (3,13) else 1)" >nul 2>&1
exit /b %errorlevel%

:fail
echo run_local_demo: %~1 1>&2
exit /b 1
