#define MyAppName "LabMonitor"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "LabMonitor"

[Setup]
AppId={{B93D7648-7F1B-4E76-A13C-88D55C68C1A4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\LabMonitor
DefaultGroupName=LabMonitor
OutputDir=output
OutputBaseFilename=LabMonitor_Setup_Test
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\Student\LabMonitorStudent.exe

[Files]
Source: "..\dist\LabMonitorAgent\*"; DestDir: "{app}\Agent"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\LabMonitorStudent\*"; DestDir: "{app}\Student"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "ConfigureAssignedAccess.ps1"; DestDir: "{app}\Tools"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\LabMonitor"; Filename: "{app}\Student\LabMonitorStudent.exe"

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\Tools\ConfigureAssignedAccess.ps1"" -Operation Remove -StudentAccount unused"; Check: FileExists(ExpandConstant('{app}\Tools\ConfigureAssignedAccess.ps1')); Flags: runhidden waituntilterminated; RunOnceId: "RemoveLabMonitorAssignedAccess"

[Code]
var
  ServerPage: TInputQueryWizardPage;
  CommandResult: Integer;

procedure InitializeWizard;
begin
  ServerPage := CreateInputQueryPage(
    wpSelectDir,
    'Servidor de LabMonitor',
    'Ingresa la direccion del servidor LabMonitor.',
    'El administrador autorizara el registro del equipo al iniciar LabMonitor por primera vez.'
  );
  ServerPage.Add('URL del servidor:', False);
  ServerPage.Values[0] := 'http://127.0.0.1:8000';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ServerUrl: String;
begin
  Result := True;
  if CurPageID = ServerPage.ID then begin
    ServerUrl := Trim(ServerPage.Values[0]);
    if ServerUrl = '' then begin
      MsgBox('Ingresa la URL del servidor.', mbError, MB_OK);
      Result := False;
    end else if (Pos('http://', Lowercase(ServerUrl)) <> 1) and
                (Pos('https://', Lowercase(ServerUrl)) <> 1) then begin
      MsgBox('La URL debe comenzar con http:// o https://.', mbError, MB_OK);
      Result := False;
    end else if (Pos(' ', ServerUrl) > 0) or
                (Pos('"', ServerUrl) > 0) or
                (Pos(#13, ServerUrl) > 0) or
                (Pos(#10, ServerUrl) > 0) or
                (Pos('?', ServerUrl) > 0) or
                (Pos('#', ServerUrl) > 0) then begin
      MsgBox('La URL del servidor contiene caracteres no permitidos.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure RequireCommandSuccess(const Description: String; const ResultCode: Integer);
begin
  if ResultCode <> 0 then
    RaiseException(Description + ' (codigo ' + IntToStr(ResultCode) + ').');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AgentExe: String;
  AgentConfigFile: String;
  ClientConfigFile: String;
  ServerConfig: String;
begin
  if CurStep = ssPostInstall then begin
    if not ForceDirectories(ExpandConstant('{commonappdata}\LabMonitor')) then
      RaiseException('No fue posible crear la carpeta de configuracion de LabMonitor.');
    ServerConfig := Trim(ServerPage.Values[0]);
    AgentConfigFile := ExpandConstant('{commonappdata}\LabMonitor\agent.env');
    ClientConfigFile := ExpandConstant('{commonappdata}\LabMonitor\client.env');
    if not FileExists(AgentConfigFile) then begin
      if not SaveStringToFile(
        AgentConfigFile,
        'LABMONITOR_SERVER_URL=' + ServerConfig + #13#10 +
        'SERVER_URL=' + ServerConfig + #13#10,
        False
      ) then
        RaiseException('No fue posible guardar la direccion del servidor para el agente.');
    end;
    if not SaveStringToFile(
      ClientConfigFile,
      'LABMONITOR_SERVER_URL=' + ServerConfig + #13#10,
      False
    ) then
      RaiseException('No fue posible guardar la direccion del servidor para LabMonitor Students.');
    if not DeleteFile(
      ExpandConstant('{commonstartup}\LabMonitor.lnk')
    ) and FileExists(
      ExpandConstant('{commonstartup}\LabMonitor.lnk')
    ) then
      RaiseException('No fue posible quitar el inicio general de LabMonitor. Reinicia el instalador como administrador.');
    if not Exec(
      ExpandConstant('{sys}\icacls.exe'),
      '"' + AgentConfigFile + '" /inheritance:r /grant:r *S-1-5-18:F *S-1-5-32-544:F',
      '', SW_HIDE, ewWaitUntilTerminated, CommandResult
    ) then
      RaiseException('No fue posible proteger la configuracion privada del agente.');
    RequireCommandSuccess('No fue posible proteger la configuracion privada del agente', CommandResult);
    if not Exec(
      ExpandConstant('{sys}\icacls.exe'),
      '"' + ClientConfigFile + '" /inheritance:r /grant:r *S-1-5-18:F *S-1-5-32-544:F *S-1-5-11:R',
      '', SW_HIDE, ewWaitUntilTerminated, CommandResult
    ) then
      RaiseException('No fue posible proteger la configuracion del cliente.');
    RequireCommandSuccess('No fue posible proteger la configuracion del cliente', CommandResult);

    AgentExe := ExpandConstant('{app}\Agent\LabMonitorAgent.exe');
    if not Exec(
      AgentExe, '--startup auto install', ExpandConstant('{app}\Agent'),
      SW_HIDE, ewWaitUntilTerminated, CommandResult
    ) then
      RaiseException('No fue posible instalar el servicio LabMonitorAgent.');
    RequireCommandSuccess('No fue posible instalar/actualizar LabMonitorAgent', CommandResult);

    if not Exec(
      AgentExe, '--wait 30 start', ExpandConstant('{app}\Agent'),
      SW_HIDE, ewWaitUntilTerminated, CommandResult
    ) then
      RaiseException('No fue posible iniciar el servicio LabMonitorAgent.');
    RequireCommandSuccess('No fue posible iniciar LabMonitorAgent', CommandResult);
    MsgBox(
      'LabMonitor se instalo correctamente. Inicia sesion en la cuenta de Windows que usaran los alumnos y abre LabMonitor desde el menu Inicio. Al configurar el equipo con una cuenta administradora de LabMonitor, LabMonitor se abrira a pantalla completa. Windows puede limitar el acceso a otras aplicaciones solo si la cuenta es estandar y la edicion de Windows admite Acceso asignado; en caso contrario, la app seguira funcionando pero Windows no quedara bloqueado.',
      mbInformation,
      MB_OK
    );
  end;
end;
