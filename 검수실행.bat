@echo off
setlocal enabledelayedexpansion
set SCRIPTS=%~dp0scripts
if "%~1"=="" (
  echo.
  echo  사용법: hwpx 파일 1~2개를 이 파일 위에 끌어다 놓으세요.
  echo    1개면 검산만, 2개면 첫 번째=평가, 두 번째=일반으로 교차 검수까지.
  echo  결과: 원본 옆에 _items.json / _report.json 생성
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
python "%SCRIPTS%\math_review.py" %JSONS% --out "%~dpn1_report.json" || goto :err
echo.
echo 완료. 보고서: %~dpn1_report.json
echo    high 결함은 문항id를 한글에서 열어 확인, 판정불가는 정독 대상 목록.
pause
exit /b 0
:err
echo.
echo 오류 발생. 위 메시지를 확인하세요. Python, lxml, sympy 설치 여부 포함.
pause
exit /b 1
