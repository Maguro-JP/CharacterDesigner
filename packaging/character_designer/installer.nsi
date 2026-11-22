; CharacterDesigner（AtelIer の拡張）の Setup.exe。build.sh から makensis で組む（SRC、OUT、VERSION を渡す）
;
; 置き場
;   C:\Program Files\CharacterDesigner\                    拡張の中身の控え（入れ直すたびに丸ごと置き換える）
;   C:\ProgramData\AtelIer\extensions\character_designer\  AtelIer が起動のときに読む置き場（AtelIer が入っているときだけ）
;
; AtelIer が入っているかは HKLM\Software\AtelIer の InstallDir で見る。無ければ AtelIer の置き場には何もしない。
; 更新: 拡張の置き場を消してから置き直す。版を上げたときに消したファイルが残って古いまま読まれないように
; 消す: 控え、拡張の置き場、登録を消す。描いた物と設定資料（AtelIer のデータの置き場）は消さない
Target amd64-unicode
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"

!define APP "CharacterDesigner"
!define UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"
!define EXT "$COMMONPROGRAMDATA\AtelIer\extensions\character_designer"

Name "${APP}"
OutFile "${OUT}"
InstallDir "$PROGRAMFILES64\${APP}"
InstallDirRegKey HKLM "Software\${APP}" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Japanese"

Var ATELIER

Section "Install"
  SetShellVarContext all
  ; 前の版（chatdraw を入れていた版）の物も含めて、前の中身を先に消す
  RMDir /r "$INSTDIR\character_designer"
  RMDir /r "$INSTDIR\chatdraw"
  RMDir /r "$INSTDIR\tools"
  RMDir /r "$INSTDIR\styles"
  RMDir /r "$INSTDIR\casts"
  SetOutPath "$INSTDIR"
  File /r "${SRC}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; AtelIer があれば、AtelIer の拡張の置き場に入れる
  SetRegView 64
  ReadRegStr $ATELIER HKLM "Software\AtelIer" "InstallDir"
  ${If} $ATELIER != ""
    DetailPrint "AtelIer に拡張を入れています: ${EXT}"
    RMDir /r "${EXT}"
    CreateDirectory "${EXT}"
    CopyFiles /SILENT "$INSTDIR\character_designer" "${EXT}"
    CopyFiles /SILENT "$INSTDIR\tools" "${EXT}"
    CopyFiles /SILENT "$INSTDIR\styles" "${EXT}"
    CopyFiles /SILENT "$INSTDIR\casts" "${EXT}"
    CopyFiles /SILENT "$INSTDIR\extension.json" "${EXT}"
    CopyFiles /SILENT "$INSTDIR\VERSION" "${EXT}"
    CopyFiles /SILENT "$INSTDIR\LICENSE" "${EXT}"
  ${Else}
    DetailPrint "AtelIer が入っていないので、AtelIer の拡張は入れません"
  ${EndIf}

  WriteRegStr HKLM "Software\${APP}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${UNINST}" "DisplayName" "${APP}"
  WriteRegStr HKLM "${UNINST}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "${UNINST}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext all
  SetRegView 64
  RMDir /r "${EXT}"
  RMDir "$COMMONPROGRAMDATA\AtelIer\extensions"
  RMDir /r "$INSTDIR\character_designer"
  RMDir /r "$INSTDIR\tools"
  RMDir /r "$INSTDIR\styles"
  RMDir /r "$INSTDIR\casts"
  Delete "$INSTDIR\extension.json"
  Delete "$INSTDIR\VERSION"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "${UNINST}"
  DeleteRegKey HKLM "Software\${APP}"
SectionEnd
