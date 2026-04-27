@echo off
setlocal

yt-dlp --update-to nightly

:input
set /p URL=Enter video or playlist URL: 

if "%URL%"=="" (
    echo URL cannot be empty, please try again.
    goto input
)

echo.
echo Downloading from: %URL%
echo.

yt-dlp ^
    -f "bv*[height=1080][ext=mp4]+ba[ext=m4a]/bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]" ^
    --merge-output-format mp4 ^
    --yes-playlist ^
    --write-thumbnail ^
    --write-subs ^
    "%URL%"

echo.

for %%f in (*.webp) do (
    ren "%%f" "%%~nf.png"
)

endlocal
