; CharacterDesigner（AtelIer の拡張）の Setup.exe。build.sh から makensis で組む（SRC、OUT、VERSION を渡す）
;
; 置き場
;   C:\Program Files\CharacterDesigner\                    拡張の中身の控え（入れ直すたびに丸ごと置き換える）
;   C:\ProgramData\AtelIer\extensions\character_designer\  AtelIer が起動のときに読む置き場（AtelIer が入っているときだけ）
;
; AtelIer が入っているかは HKLM\Software\AtelIer の InstallDir で見る。無ければ AtelIer の置き場には何もしない。
; 更新: 拡張の置き場を消してから置き直す。版を上げたときに消したファイルが残って古いまま読まれないように
; 消す: 控え、拡張の置き場、登録を消す。描いた物と設定資料（AtelIer のデータの置き場）は消さない
;
; 消すのは、このアプリが入れた名前だけで、その印がある所に限る。インストール先や置き場そのものを /r で消さない。
; 利用者が選んだ既存のフォルダー（同じ名前の tools などを持つ所）や、前の版のデータの置き場
; （C:\ProgramData\CharacterDesigner の library、資料、記録、作業ファイル）、C:\LLM、AtelIer の置き場、
; ほかの拡張を巻き込まないため。どの答えを選んでも、利用者の物は消さない
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

; 控え（インストール先）から、この Setup が入れた物だけを消す。並びは build.sh が SRC に置く最上位の名前と同じにする。
; 印（extension.json と character_designer\__init__.py）が無い所では何も消さない
!macro RemoveAppFiles
  ${If} ${FileExists} "$INSTDIR\extension.json"
  ${AndIf} ${FileExists} "$INSTDIR\character_designer\__init__.py"
    RMDir /r "$INSTDIR\character_designer"
    RMDir /r "$INSTDIR\tools"
    RMDir /r "$INSTDIR\styles"
    RMDir /r "$INSTDIR\casts"
    Delete "$INSTDIR\extension.json"
    Delete "$INSTDIR\VERSION"
    Delete "$INSTDIR\LICENSE"
  ${EndIf}
!macroend

; 前の版（単体の Setup。chatdraw と python を入れていた）のプログラムとショートカットを消す。
; 印（VERSION と chatdraw\__init__.py）がある所だけ。データの置き場（ProgramData\CharacterDesigner）と C:\LLM には触らない
!macro RemoveOldSingleApp
  ${If} ${FileExists} "$INSTDIR\VERSION"
  ${AndIf} ${FileExists} "$INSTDIR\chatdraw\__init__.py"
    RMDir /r "$INSTDIR\chatdraw"
    RMDir /r "$INSTDIR\tools"
    RMDir /r "$INSTDIR\python"
    Delete "$INSTDIR\VERSION"
    Delete "$INSTDIR\LICENSE"
    Delete "$SMPROGRAMS\${APP}\${APP}.lnk"
    Delete "$SMPROGRAMS\${APP}\Uninstall.lnk"
    RMDir "$SMPROGRAMS\${APP}"
    Delete "$DESKTOP\${APP}.lnk"
  ${EndIf}
!macroend

; AtelIer の拡張の置き場から、この拡張のフォルダーだけを消す。印（extension.json）がある時だけ
!macro RemoveExtension
  ${If} ${FileExists} "${EXT}\extension.json"
    RMDir /r "${EXT}"
  ${EndIf}
!macroend

Section "Install"
  SetShellVarContext all
  ; 前の中身を先に消す。消すのは印のある所の、アプリが入れた名前だけ（RemoveAppFiles、RemoveOldSingleApp）
  !insertmacro RemoveAppFiles
  !insertmacro RemoveOldSingleApp
  SetOutPath "$INSTDIR"
  File /r "${SRC}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; AtelIer があれば、AtelIer の拡張の置き場に入れる
  SetRegView 64
  ReadRegStr $ATELIER HKLM "Software\AtelIer" "InstallDir"
  ${If} $ATELIER != ""
    DetailPrint "AtelIer に拡張を入れています: ${EXT}"
    !insertmacro RemoveExtension
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
  !insertmacro RemoveExtension
  RMDir "$COMMONPROGRAMDATA\AtelIer\extensions"
  !insertmacro RemoveAppFiles
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "${UNINST}"
  DeleteRegKey HKLM "Software\${APP}"
SectionEnd
