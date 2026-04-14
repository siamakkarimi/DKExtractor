[Setup]
AppName=DKExtractor
AppVersion=1.0.0
DefaultDirName={autopf}\DKExtractor
DefaultGroupName=DKExtractor
OutputDir=installer_output
OutputBaseFilename=Setup_DKExtractor
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "dist\DKExtractor\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\DKExtractor"; Filename: "{app}\DKExtractor.exe"
Name: "{autodesktop}\DKExtractor"; Filename: "{app}\DKExtractor.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\DKExtractor.exe"; Description: "Launch DKExtractor"; Flags: nowait postinstall skipifsilent
