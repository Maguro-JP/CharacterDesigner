; CharacterDesigner の Setup.exe。build.sh から makensis で組む（SRC、OUT、VERSION を渡す）
; 利用者ごとの場所に入れるので管理者の権限は要らない。描く部品と絵の模型は入れた場所の .cache に置く（初回の起動で取る）
; 中身の Python が amd64 なので、Setup.exe も 64 ビットにそろえる
Target amd64-unicode
!include "MUI2.nsh"

Name "CharacterDesigner"
OutFile "${OUT}"
InstallDir "$LOCALAPPDATA\Programs\CharacterDesigner"
RequestExecutionLevel user
SetCompressor /SOLID lzma

!define MUI_FINISHPAGE_RUN "$INSTDIR\CharacterDesigner.cmd"
!define MUI_FINISHPAGE_RUN_TEXT "CharacterDesigner を起動する（初回は部品と絵の模型 約 10GB を取ります）"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Japanese"
!insertmacro MUI_LANGUAGE "English"

!define UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\CharacterDesigner"

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "${SRC}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\CharacterDesigner"
  CreateShortcut "$SMPROGRAMS\CharacterDesigner\CharacterDesigner.lnk" "$INSTDIR\CharacterDesigner.cmd" "" "$INSTDIR\python\python.exe"
  CreateShortcut "$SMPROGRAMS\CharacterDesigner\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\CharacterDesigner.lnk" "$INSTDIR\CharacterDesigner.cmd" "" "$INSTDIR\python\python.exe"
  WriteRegStr HKCU "${UNINST}" "DisplayName" "CharacterDesigner"
  WriteRegStr HKCU "${UNINST}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  ; 描いた絵・保存した設定資料・取った部品と絵の模型は、消すと戻せない。既定は残し、入れたもの（プログラム）だけを消す。
  ; 残す場所の一覧は build.sh が書く（uninstall-files.nsh。DATA に挙げたものを除いた、入れたもの全部）
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "描いた絵・保存したキャラクター・取った絵の模型も消しますか？$\r$\n消すと戻せません。残す場合は「いいえ」を選んでください（$INSTDIR に残ります）。" /SD IDNO IDYES remove_all
  !include "${SRC}\..\uninstall-files.nsh"
  Goto shortcuts
  remove_all:
    RMDir /r "$INSTDIR"
  shortcuts:
  Delete "$SMPROGRAMS\CharacterDesigner\*.lnk"
  RMDir "$SMPROGRAMS\CharacterDesigner"
  Delete "$DESKTOP\CharacterDesigner.lnk"
  DeleteRegKey HKCU "${UNINST}"
SectionEnd
