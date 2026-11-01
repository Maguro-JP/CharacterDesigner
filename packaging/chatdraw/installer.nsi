; chatdraw（CharacterDesigner）の Setup.exe。build.sh から makensis で組む（SRC、OUT、VERSION を渡す）
;
; 置き場（chatdraw/paths.py と同じ。自作の AdaptiveAIStudio にそろえる）
;   C:\Program Files\CharacterDesigner\      プログラム（入れ直すたびに丸ごと置き換える）
;   C:\ProgramData\CharacterDesigner\        部品（torch など。初回の起動で取る）と記録
;   C:\LLM\gguf、C:\LLM\huggingface          模型（自作アプリで共有。消さない）
;   ピクチャ\CharacterDesigner\              描いた絵
;
; 入れる: 前の版（%LOCALAPPDATA%\Programs\CharacterDesigner）があれば、模型と描いた物を新しい置き場へ移してから、前の版を消す
; 更新: 同じ場所に入れ直す。前のプログラムを消してから置くので、古いファイルが残らない。部品・模型・描いた絵はそのまま
; 消す: プログラム、ショートカット、登録を消す。部品（ProgramData）は聞いてから消す。利用者の設定（QSettings と ProgramData の設定のファイル）、模型、描いた絵は消さない
Target amd64-unicode
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"

!define APP "CharacterDesigner"
!define UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"

Name "${APP}"
OutFile "${OUT}"
InstallDir "$PROGRAMFILES64\${APP}"
InstallDirRegKey HKLM "Software\${APP}" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

; アプリのアイコン。build.sh が chatdraw/icon/app.png（利用者が選んだ絵）から .ico を作ったときだけ ICON を渡す。
; 無い間は今まで通り pythonw.exe のアイコンのまま
!ifdef ICON
  !define MUI_ICON "${ICON}"
  !define MUI_UNICON "${ICON}"
  !define LNK_ICON "$INSTDIR\chatdraw\icon\app.ico"
!else
  !define LNK_ICON "$INSTDIR\python\pythonw.exe"
!endif

!define MUI_FINISHPAGE_RUN "$INSTDIR\python\pythonw.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "-E -s -m chatdraw.app"
!define MUI_FINISHPAGE_RUN_TEXT "CharacterDesigner を起動する"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Japanese"

Var OLD

Section "Install"
  ; 更新のとき、前のプログラムを先に消す（消したファイルが残って古いまま読まれないように）
  RMDir /r "$INSTDIR\chatdraw"
  RMDir /r "$INSTDIR\tools"
  RMDir /r "$INSTDIR\python"
  SetOutPath "$INSTDIR"
  File /r "${SRC}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; 書き換える置き場。ふつうの利用者も書けるようにする（ProgramData と C:\ 直下は既定で管理者しか書けない）
  CreateDirectory "$COMMONPROGRAMDATA\${APP}"
  nsExec::ExecToLog '"$SYSDIR\icacls.exe" "$COMMONPROGRAMDATA\${APP}" /grant *S-1-5-32-545:(OI)(CI)M /T /Q'
  ; 模型の置き場はシステムのドライブの LLM（アプリの paths.default_model_dir と同じ。C: 以外にも合わせる）
  StrCpy $1 "$WINDIR" 3
  CreateDirectory "$1LLM\gguf"
  CreateDirectory "$1LLM\huggingface"
  CreateDirectory "$1LLM\manual"
  nsExec::ExecToLog '"$SYSDIR\icacls.exe" "$1LLM" /grant *S-1-5-32-545:(OI)(CI)M /Q'

  ; 前の版からの移行。前の版は利用者ごとに入れていたので、HKCU の登録から場所を読む
  SetShellVarContext current
  ReadRegStr $OLD HKCU "${UNINST}" "InstallLocation"
  StrCmp $OLD "" 0 +2
    StrCpy $OLD "$LOCALAPPDATA\Programs\${APP}"
  IfFileExists "$OLD\*.*" 0 no_old
    DetailPrint "前の版を移しています: $OLD"
    nsExec::ExecToLog '"$INSTDIR\python\python.exe" -m chatdraw.migrate "$OLD"'
    Pop $0
    StrCmp $0 "0" 0 migrate_failed
      Delete "$SMPROGRAMS\${APP}\*.lnk"
      RMDir "$SMPROGRAMS\${APP}"
      Delete "$DESKTOP\${APP}.lnk"
      DeleteRegKey HKCU "${UNINST}"
      Goto no_old
    migrate_failed:
      MessageBox MB_OK|MB_ICONEXCLAMATION "前の版の一部を移せなかったので、前の版はそのまま残しました。$\r$\n記録: $COMMONPROGRAMDATA\${APP}\migrate.log"
  no_old:

  SetShellVarContext all
  SetOutPath "$INSTDIR"
  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\python\pythonw.exe" "-E -s -m chatdraw.app" "${LNK_ICON}"
  CreateShortcut "$SMPROGRAMS\${APP}\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\python\pythonw.exe" "-E -s -m chatdraw.app" "${LNK_ICON}"

  WriteRegStr HKLM "Software\${APP}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${UNINST}" "DisplayName" "${APP}"
  WriteRegStr HKLM "${UNINST}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINST}" "DisplayIcon" "${LNK_ICON}"
  WriteRegStr HKLM "${UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "${UNINST}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  ; 入れた所は丸ごと消す（__pycache__ など起動で出来た物も残さない）。名前が違う所に入れたときは、入れた物だけを消す
  RMDir /r "$INSTDIR\chatdraw"
  RMDir /r "$INSTDIR\tools"
  RMDir /r "$INSTDIR\python"
  Delete "$INSTDIR\VERSION"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\Uninstall.exe"
  ${If} ${FileExists} "$INSTDIR\*.*"
  ${AndIf} "$INSTDIR" == "$PROGRAMFILES64\${APP}"
    RMDir /r "$INSTDIR"
  ${EndIf}
  RMDir "$INSTDIR"
  SetShellVarContext all
  ; 取った更新の Setup.exe と自動保存の控えは、部品を残すときも消す（作業ファイルではなく一時の物）
  RMDir /r "$COMMONPROGRAMDATA\${APP}\updates"
  RMDir /r "$COMMONPROGRAMDATA\${APP}\autosave"
  Delete "$SMPROGRAMS\${APP}\*.lnk"
  RMDir /r "$SMPROGRAMS\${APP}"
  Delete "$DESKTOP\${APP}.lnk"
  DeleteRegKey HKLM "${UNINST}"
  DeleteRegKey HKLM "Software\${APP}"
  ; 窓の並びと設定（QSettings が HKCU\Software\CharacterDesigner に書く）は消さない。入れ直したときに引き継ぐ
  ; 部品（torch など 数 GB）は取り直せるので、聞いてから消す。利用者の設定（★・非表示・ブロック・点・タグ・絵の ★・
  ; 模型の置き場・学んだ基準・ごみ箱）は消さずに残す。黙って消す（/S）ときは何も消さない
  MessageBox MB_YESNO|MB_ICONQUESTION "絵を描く部品（$COMMONPROGRAMDATA\${APP}）も消しますか？$\r$\n部品は、入れ直したときに取り直せます。お気に入りや非表示などの設定は消さずに残します。描いた絵と模型はここには入っていません。" /SD IDNO IDNO keep_data
    StrCpy $1 "$COMMONPROGRAMDATA\${APP}"
    StrCpy $2 "$COMMONPROGRAMDATA\${APP}.keep"
    RMDir /r "$2"
    CreateDirectory "$2"
    Rename "$1\model_prefs.json" "$2\model_prefs.json"
    Rename "$1\favorites.json" "$2\favorites.json"
    Rename "$1\places.json" "$2\places.json"
    Rename "$1\learn" "$2\learn"
    Rename "$1\trash" "$2\trash"
    CreateDirectory "$2\cd"
    Rename "$1\cd\model_prefs.json" "$2\cd\model_prefs.json"
    Rename "$1\cd\favorites.json" "$2\cd\favorites.json"
    Rename "$1\cd\places.json" "$2\cd\places.json"
    Rename "$1\cd\learn" "$2\cd\learn"
    RMDir /r "$1"
    Rename "$2" "$1"
  keep_data:
  MessageBox MB_OK|MB_ICONINFORMATION "アンインストールしました。$\r$\n$\r$\n次の物は残してあります。$\r$\n描いた絵: ピクチャの ${APP} フォルダー$\r$\n模型: C:\LLM（ほかの自作アプリも使うため。要らなければフォルダーごと消せます）" /SD IDOK
SectionEnd
