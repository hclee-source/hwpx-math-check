@echo off
setlocal enabledelayedexpansion
set SCRIPTS=%~dp0scripts
if "%~1"=="" (
  echo.
  echo  사용법: hwpx 파일 1~2개를 이 파일 위에 끌어다 놓거나,
  echo  우클릭 - 보내기 - 문항검수 를 쓰세요. 창이 싫으면 검수도우미.pyw 더블클릭.
  echo.
  pause
  exit /b 1
)
set JSONS=
for %%F in (%*) do (
  echo [파싱] %%~nxF
  python "%SCRIPTS%\hwpx_items.py" "%%~fF" --out "%%~dpnF_items.json" || goto :err
  set JSONS=!JSONS! "%%~dpnF_items.json"
)
echo.
echo [검수] 정답-해설 검산 + 조판 결함 + 쌍둥이 교차...
python "%SCRIPTS%\math_review.py" %JSONS% --out "%~dpn1_report.json" --html "%~dpn1_검수보고서.html" || goto :err
echo.
echo 완료. 보고서를 브라우저로 엽니다.
start "" "%~dpn1_검수보고서.html"
timeout /t 3 >nul
exit /b 0
:err
echo.
echo 오류 발생. 위 메시지를 확인하세요. Python, lxml, sympy 설치 여부 포함.
pause
exit /b 1
