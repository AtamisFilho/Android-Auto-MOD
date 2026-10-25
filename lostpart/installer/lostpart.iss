; lostpart - Windows installer
;
; Compiled with:
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" lostpart.generated.iss
;
; The installation is per user: it never asks for administrator rights and
; it never touches the machine wide PATH.
;
; scripts/build.py copies this file to lostpart.generated.iss with the
; version of the package substituted, so the two never drift apart.

#define AppName "lostpart"
#define AppVersion "0.2.0"
#define AppPublisher "Atamis Filho"
#define AppURL "https://github.com/AtamisFilho/testes"
#define AppExeName "lostpart.exe"

[Setup]
AppId={{7C4E2B19-8A31-4C0D-9E77-6B2D51F0A3C8}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=lostpart-installer
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=..\assets\lostpart.ico
MinVersion=10.0
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "addtopath"; Description: "Add lostpart to the PATH environment variable"; \
    GroupDescription: "Additional tasks:"; Flags: unchecked
Name: "desktopicon"; Description: "Create a desktop shortcut"; \
    GroupDescription: "Additional tasks:"; Flags: unchecked

[Files]
Source: "..\dist\lostpart-windows-x64.exe"; DestDir: "{app}"; \
    DestName: "{#AppExeName}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; DestName: "README.md"; \
    Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE"; \
    Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{group}\Documentation"; Filename: "{app}\README.md"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}')); \
    Tasks: addtopath

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Start lostpart"; \
    Flags: nowait postinstall skipifsilent

[Code]
{ Adds the directory to the PATH only when it is not there yet. }
function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and (not WizardSilent) then
  begin
    if WizardIsTaskSelected('addtopath') then
      WizardForm.FinishedLabel.Caption :=
        WizardForm.FinishedLabel.Caption + #13#13 +
        'The PATH was updated. Open a new terminal for it to take effect.';
  end;
end;
