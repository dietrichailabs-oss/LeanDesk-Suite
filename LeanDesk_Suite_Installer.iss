#ifndef SourceRoot
  #define SourceRoot "Release\v0.8.1"
#endif
#ifndef OutputRoot
  #define OutputRoot "Release\v0.8.1"
#endif

#define MyAppName "LeanDesk Suite"
#define MyAppVersion "0.8.1"
#define MyAppPublisher "Dietrich AI Labs"
#define MyAppExeName "LeanDesk_Suite.exe"

[Setup]
AppId={{5CF8DB83-83B2-4A42-9806-267E05B91782}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\LeanDesk Suite
DefaultGroupName=LeanDesk Suite
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputRoot}
OutputBaseFilename=LeanDesk_Suite_Setup_0.8.1
SetupIconFile={#SourceRoot}\lean_desk_suite.ico
UninstallDisplayIcon={app}\lean_desk_suite.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
LicenseFile=EULA.txt
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion=0.8.1.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=LeanDesk Suite Installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "associations"; Description: "Associate LeanDesk native document types"; GroupDescription: "File associations:"; Flags: unchecked

[Files]
Source: "{#SourceRoot}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\lean_desk_suite.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "EULA.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\Dietrich_AI_Labs_Public_Certificate.cer"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
Root: HKCU; Subkey: "Software\Classes\.ldoc"; ValueType: string; ValueData: "LeanDesk.Writer"; Flags: uninsdeletevalue; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\LeanDesk.Writer"; ValueType: string; ValueData: "LeanDesk Writer Document"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\LeanDesk.Writer\DefaultIcon"; ValueType: string; ValueData: "{app}\lean_desk_suite.ico"
Root: HKCU; Subkey: "Software\Classes\LeanDesk.Writer\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.lsheet"; ValueType: string; ValueData: "LeanDesk.Sheets"; Flags: uninsdeletevalue; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\LeanDesk.Sheets"; ValueType: string; ValueData: "LeanDesk Workbook"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\LeanDesk.Sheets\DefaultIcon"; ValueType: string; ValueData: "{app}\lean_desk_suite.ico"
Root: HKCU; Subkey: "Software\Classes\LeanDesk.Sheets\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.ldeck"; ValueType: string; ValueData: "LeanDesk.Slides"; Flags: uninsdeletevalue; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\LeanDesk.Slides"; ValueType: string; ValueData: "LeanDesk Presentation"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\LeanDesk.Slides\DefaultIcon"; ValueType: string; ValueData: "{app}\lean_desk_suite.ico"
Root: HKCU; Subkey: "Software\Classes\LeanDesk.Slides\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.ldraw"; ValueType: string; ValueData: "LeanDesk.Draw"; Flags: uninsdeletevalue; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\LeanDesk.Draw"; ValueType: string; ValueData: "LeanDesk Drawing"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\LeanDesk.Draw\DefaultIcon"; ValueType: string; ValueData: "{app}\lean_desk_suite.ico"
Root: HKCU; Subkey: "Software\Classes\LeanDesk.Draw\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "LeanDesk Suite"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "LeanDesk Suite office document editor and compatibility viewer"
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "LeanDesk Suite"; ValueData: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ldoc"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".lsheet"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ldeck"; ValueData: "LeanDesk.Slides"
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ldraw"; ValueData: "LeanDesk.Draw"
Root: HKCU; Subkey: "Software\Classes\.abw\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".abw"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.cwk\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".cwk"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.doc\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".doc"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.docm\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".docm"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.docx\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".docx"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.dot\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".dot"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.dotm\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".dotm"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.dotx\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".dotx"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.htm\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".htm"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.html\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".html"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.lwp\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".lwp"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.md\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".md"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.odt\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".odt"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.ott\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ott"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.pages\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pages"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.rtf\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".rtf"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.sxw\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".sxw"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.txt\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".txt"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.wpd\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wpd"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.wps\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Writer"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wps"; ValueData: "LeanDesk.Writer"
Root: HKCU; Subkey: "Software\Classes\.123\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".123"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.csv\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".csv"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.dbf\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".dbf"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.dif\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".dif"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.numbers\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".numbers"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.ods\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ods"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.ots\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ots"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.tsv\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".tsv"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.wk1\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wk1"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.wk3\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wk3"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.wk4\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wk4"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.wks\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wks"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.xls\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".xls"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.xlsb\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".xlsb"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.xlsm\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".xlsm"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.xlsx\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Sheets"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".xlsx"; ValueData: "LeanDesk.Sheets"
Root: HKCU; Subkey: "Software\Classes\.key\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Slides"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".key"; ValueData: "LeanDesk.Slides"
Root: HKCU; Subkey: "Software\Classes\.odp\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Slides"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".odp"; ValueData: "LeanDesk.Slides"
Root: HKCU; Subkey: "Software\Classes\.otp\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Slides"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".otp"; ValueData: "LeanDesk.Slides"
Root: HKCU; Subkey: "Software\Classes\.pps\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Slides"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pps"; ValueData: "LeanDesk.Slides"
Root: HKCU; Subkey: "Software\Classes\.ppsx\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Slides"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ppsx"; ValueData: "LeanDesk.Slides"
Root: HKCU; Subkey: "Software\Classes\.ppt\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Slides"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ppt"; ValueData: "LeanDesk.Slides"
Root: HKCU; Subkey: "Software\Classes\.pptm\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Slides"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pptm"; ValueData: "LeanDesk.Slides"
Root: HKCU; Subkey: "Software\Classes\.pptx\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Slides"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pptx"; ValueData: "LeanDesk.Slides"
Root: HKCU; Subkey: "Software\Classes\.sxi\OpenWithProgids"; ValueType: string; ValueName: "LeanDesk.Slides"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; ValueType: string; ValueName: ".sxi"; ValueData: "LeanDesk.Slides"
[Icons]
Name: "{group}\LeanDesk Suite"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\lean_desk_suite.ico"
Name: "{autodesktop}\LeanDesk Suite"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\lean_desk_suite.ico"; Tasks: desktopicon
Name: "{group}\Uninstall LeanDesk Suite"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch LeanDesk Suite"; Flags: nowait postinstall skipifsilent
