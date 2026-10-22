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
Source: "ProtectLocalAdminPassword.ps1"; DestDir: "{app}\Tools"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\LabMonitor"; Filename: "{app}\Student\LabMonitorStudent.exe"

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\Tools\ConfigureAssignedAccess.ps1"" -Operation Remove -StudentAccount unused"; Check: FileExists(ExpandConstant('{app}\Tools\ConfigureAssignedAccess.ps1')); Flags: runhidden waituntilterminated; RunOnceId: "RemoveLabMonitorAssignedAccess"

[Code]
var
  ServerPage: TInputQueryWizardPage;
  LocalAdminPage: TInputQueryWizardPage;
  CommandResult: Integer;

procedure InitializeWizard;
begin
  ServerPage := CreateInputQueryPage(
    wpSelectDir,
    'Servidor de LabMonitor',
    'Ingresa la direccion del servidor LabMonitor.',
    'En una maquina virtual, ingresa la IP del equipo donde corre el servidor y el puerto 8000. No uses 127.0.0.1 salvo que el servidor corra en esta misma maquina. El administrador autorizara el registro al iniciar LabMonitor por primera vez.'
  );
  ServerPage.Add('URL del servidor:', False);
  ServerPage.Values[0] := '';

  LocalAdminPage := CreateInputQueryPage(
    ServerPage.ID,
    'Acceso local de administrador',
    'Configura la credencial local para cambiar el servidor.',
    'Esta contraseña se protege para este equipo y permite cambiar la URL de FastAPI desde el acceso administrativo de LabMonitor, incluso si el servidor actual no responde. El usuario local será Sistemas_Admin. No reutilices la contraseña de otra cuenta.'
  );
  LocalAdminPage.Add('Contraseña local (mínimo 14 caracteres ASCII):', True);
  LocalAdminPage.Add('Confirmar contraseña local:', True);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ServerUrl: String;
  LocalAdminPassword: String;
  PasswordCharIndex: Integer;
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
  end else if CurPageID = LocalAdminPage.ID then begin
    LocalAdminPassword := LocalAdminPage.Values[0];
    if Length(LocalAdminPassword) < 14 then begin
      MsgBox('La contraseña local debe tener al menos 14 caracteres.', mbError, MB_OK);
      Result := False;
    end else begin
      for PasswordCharIndex := 1 to Length(LocalAdminPassword) do begin
        if (Ord(LocalAdminPassword[PasswordCharIndex]) < 32) or
           (Ord(LocalAdminPassword[PasswordCharIndex]) > 126) then begin
          MsgBox('Usa caracteres ASCII visibles en la contraseña local.', mbError, MB_OK);
          Result := False;
          Exit;
        end;
      end;
    end;
    if Result and
       (LocalAdminPassword <> LocalAdminPage.Values[1]) then begin
      MsgBox('Las contraseñas locales no coinciden.', mbError, MB_OK);
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
  AgentConfigLines: TArrayOfString;
  SecretOutputLines: TArrayOfString;
  AgentConfigIndex: Integer;
  AgentServerUrlFound: Boolean;
  LocalAdminSecretFound: Boolean;
  ClientConfigFile: String;
  ServerConfig: String;
  LocalAdminPassword: String;
  LocalAdminSecret: String;
  PasswordTempFile: String;
  SecretOutputFile: String;
  PasswordProtectorScript: String;
begin
  if CurStep = ssPostInstall then begin
    if not ForceDirectories(ExpandConstant('{commonappdata}\LabMonitor')) then
      RaiseException('No fue posible crear la carpeta de configuracion de LabMonitor.');
    ServerConfig := Trim(ServerPage.Values[0]);
    LocalAdminPassword := LocalAdminPage.Values[0];
    PasswordTempFile := ExpandConstant('{tmp}\LabMonitorLocalAdminPassword.tmp');
    SecretOutputFile := ExpandConstant('{tmp}\LabMonitorLocalAdminSecret.tmp');
    PasswordProtectorScript := ExpandConstant('{app}\Tools\ProtectLocalAdminPassword.ps1');
    if not SaveStringToFile(PasswordTempFile, LocalAdminPassword, False) then
      RaiseException('No fue posible preparar la contraseña local protegida.');
    if not Exec(
      ExpandConstant('{sys}\icacls.exe'),
      '"' + PasswordTempFile +
        '" /inheritance:r /grant:r *S-1-5-18:F *S-1-5-32-544:F',
      '', SW_HIDE, ewWaitUntilTerminated, CommandResult
    ) then
      RaiseException('No fue posible proteger temporalmente la contraseña local.');
    RequireCommandSuccess('No fue posible proteger temporalmente la contraseña local', CommandResult);
    if not Exec(
      ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
        PasswordProtectorScript + '" -InputPath "' + PasswordTempFile +
        '" -OutputPath "' + SecretOutputFile + '"',
      '', SW_HIDE, ewWaitUntilTerminated, CommandResult
    ) then
      RaiseException('No fue posible proteger la contraseña local de administrador.');
    RequireCommandSuccess('No fue posible proteger la contraseña local de administrador', CommandResult);
    if not LoadStringsFromFile(SecretOutputFile, SecretOutputLines) then
      RaiseException('No fue posible leer la contraseña local protegida.');
    if GetArrayLength(SecretOutputLines) = 0 then
      RaiseException('La protección de la contraseña local devolvió un resultado vacío.');
    LocalAdminSecret := Trim(SecretOutputLines[0]);
    if LocalAdminSecret = '' then
      RaiseException('La protección de la contraseña local devolvió un resultado vacío.');
    DeleteFile(PasswordTempFile);
    DeleteFile(SecretOutputFile);

    AgentConfigFile := ExpandConstant('{commonappdata}\LabMonitor\agent.env');
    ClientConfigFile := ExpandConstant('{commonappdata}\LabMonitor\client.env');
    if FileExists(AgentConfigFile) then begin
      if not LoadStringsFromFile(AgentConfigFile, AgentConfigLines) then
        RaiseException('No fue posible leer la configuracion actual del agente.');
    end else begin
      SetArrayLength(AgentConfigLines, 0);
    end;
    AgentServerUrlFound := False;
    LocalAdminSecretFound := False;
    for AgentConfigIndex := 0 to GetArrayLength(AgentConfigLines) - 1 do begin
      if (Pos('LABMONITOR_SERVER_URL=', AgentConfigLines[AgentConfigIndex]) = 1) or
         (Pos('SERVER_URL=', AgentConfigLines[AgentConfigIndex]) = 1) then begin
        AgentConfigLines[AgentConfigIndex] := 'LABMONITOR_SERVER_URL=' + ServerConfig;
        AgentServerUrlFound := True;
      end else if Pos('LABMONITOR_LOCAL_ADMIN_SECRET=', AgentConfigLines[AgentConfigIndex]) = 1 then begin
        AgentConfigLines[AgentConfigIndex] := 'LABMONITOR_LOCAL_ADMIN_SECRET=' + LocalAdminSecret;
        LocalAdminSecretFound := True;
      end;
    end;
    if not AgentServerUrlFound then begin
      SetArrayLength(AgentConfigLines, GetArrayLength(AgentConfigLines) + 1);
      AgentConfigLines[GetArrayLength(AgentConfigLines) - 1] := 'LABMONITOR_SERVER_URL=' + ServerConfig;
    end;
    if not LocalAdminSecretFound then begin
      SetArrayLength(AgentConfigLines, GetArrayLength(AgentConfigLines) + 1);
      AgentConfigLines[GetArrayLength(AgentConfigLines) - 1] := 'LABMONITOR_LOCAL_ADMIN_SECRET=' + LocalAdminSecret;
    end;
    if not SaveStringsToFile(AgentConfigFile, AgentConfigLines, False) then
      RaiseException('No fue posible guardar la direccion del servidor para el agente.');
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
