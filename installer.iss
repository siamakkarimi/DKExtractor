[Setup]
AppName=DKExtractor
AppVersion=1.0.0
SourceDir=.
DefaultDirName={autopf}\DKExtractor
DefaultGroupName=DKExtractor
OutputDir=release_artifacts
OutputBaseFilename=DKExtractor_Setup_1.0.0
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "release_dist\DKExtractor\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\DKExtractor"; Filename: "{app}\DKExtractor.exe"
Name: "{autodesktop}\DKExtractor"; Filename: "{app}\DKExtractor.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\DKExtractor.exe"; Description: "Launch DKExtractor"; Flags: nowait postinstall skipifsilent
