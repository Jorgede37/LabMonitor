[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$StudentAccount,

    [string]$StudentExePath,

    [ValidateSet('Apply', 'Remove')]
    [string]$Operation = 'Apply',

    [switch]$RunAsSystem,

    [switch]$ValidateOnly,

    [switch]$CheckRequirements,

    [string]$ResultPath
)

$ErrorActionPreference = 'Stop'
$profileId = '{C5D45384-A8D1-468B-85E0-18E1B06D8E4C}'
$stateDirectory = Join-Path $env:ProgramData 'LabMonitor'
$statePath = Join-Path $stateDirectory 'assigned-access-state.json'

function Get-NormalizedXmlHash([string]$XmlText) {
    $document = New-Object System.Xml.XmlDocument
    $document.PreserveWhitespace = $false
    $document.LoadXml($XmlText)
    $normalized = $document.OuterXml
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($normalized)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [Convert]::ToBase64String($sha.ComputeHash($bytes))
    } finally {
        $sha.Dispose()
    }
}

function New-AssignedAccessXml {
    if ($StudentAccount -notmatch '^[A-Za-z0-9_.-]{1,20}$' -or
        $StudentAccount -eq '.' -or $StudentAccount -eq '..') {
        throw 'El nombre debe ser una cuenta local valida de hasta 20 caracteres.'
    }
    if ([string]::IsNullOrWhiteSpace($StudentExePath)) {
        throw 'No se indico la ruta del ejecutable LabMonitorStudent.exe.'
    }

    $account = [System.Security.SecurityElement]::Escape(
        "$env:COMPUTERNAME\$StudentAccount"
    )
    $appPath = [System.Security.SecurityElement]::Escape(
        [System.IO.Path]::GetFullPath($StudentExePath)
    )

    $xml = @"
<?xml version="1.0" encoding="utf-8"?>
<AssignedAccessConfiguration xmlns="http://schemas.microsoft.com/AssignedAccess/2017/config" xmlns:rs5="http://schemas.microsoft.com/AssignedAccess/201810/config">
  <Profiles>
    <Profile Id="$profileId" Name="LabMonitor Student">
      <AllAppsList>
        <AllowedApps>
          <App DesktopAppPath="$appPath" rs5:AutoLaunch="true" />
        </AllowedApps>
      </AllAppsList>
      <Taskbar ShowTaskbar="false" />
    </Profile>
  </Profiles>
  <Configs>
    <Config>
      <Account>$account</Account>
      <DefaultProfile Id="$profileId" />
    </Config>
  </Configs>
</AssignedAccessConfiguration>
"@

    $document = New-Object System.Xml.XmlDocument
    $document.LoadXml($xml)
    return $document
}

function Get-AssignedAccessInstance {
    return Get-CimInstance `
        -Namespace 'root\cimv2\mdm\dmmap' `
        -ClassName 'MDM_AssignedAccess'
}

function Set-AssignedAccessConfiguration([string]$Configuration) {
    $instance = Get-AssignedAccessInstance
    $instance.Configuration = [System.Net.WebUtility]::HtmlEncode($Configuration)
    Set-CimInstance -CimInstance $instance | Out-Null
}

function Test-RequiredWindowsAccount {
    $windows = Get-CimInstance Win32_OperatingSystem
    if ([int]$windows.BuildNumber -lt 17763) {
        throw 'Se requiere Windows 10 version 1809 o posterior para iniciar automaticamente una aplicacion Win32 en Acceso asignado.'
    }

    $edition = (Get-ItemProperty `
        'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').EditionID
    if ($edition -notmatch 'Professional') {
        throw 'Esta configuracion esta preparada para Windows Pro.'
    }

    $localUser = Get-LocalUser -Name $StudentAccount -ErrorAction Stop
    if (-not $localUser.Enabled) {
        throw 'La cuenta estudiantil de Windows esta deshabilitada.'
    }

    $administratorsSid = [System.Security.Principal.SecurityIdentifier]::new(
        'S-1-5-32-544'
    )
    $administrators = Get-LocalGroupMember -SID $administratorsSid.Value
    if ($administrators.SID.Value -contains $localUser.SID.Value) {
        throw 'La cuenta estudiantil debe ser estandar, no administradora.'
    }

    $administratorSids = @($administrators.SID.Value)
    $recoveryAdministrator = Get-LocalUser |
        Where-Object {
            $_.Enabled -and
            $_.SID.Value -ne $localUser.SID.Value -and
            $administratorSids -contains $_.SID.Value
        } |
        Select-Object -First 1
    if (-not $recoveryAdministrator) {
        throw 'Crea o habilita otra cuenta local administradora de Windows antes de activar el quiosco. Esa cuenta será necesaria para recuperar el equipo.'
    }
}

function Invoke-SystemOperation {
    if ($Operation -eq 'Apply') {
        if ($StudentAccount -notmatch '^[A-Za-z0-9_.-]{1,20}$' -or
            $StudentAccount -eq '.' -or $StudentAccount -eq '..') {
            throw 'El nombre debe ser una cuenta local valida de hasta 20 caracteres.'
        }

        Test-RequiredWindowsAccount

        if (-not (Test-Path -LiteralPath $StudentExePath -PathType Leaf)) {
            throw "No se encontro el ejecutable: $StudentExePath"
        }

        $document = New-AssignedAccessXml
        $configuration = $document.OuterXml
        $newHash = Get-NormalizedXmlHash $configuration
        $instance = Get-AssignedAccessInstance
        $currentConfiguration = [string]$instance.Configuration
        $currentHash = ''
        if (-not [string]::IsNullOrWhiteSpace($currentConfiguration)) {
            $currentXml = [System.Net.WebUtility]::HtmlDecode($currentConfiguration)
            $currentHash = Get-NormalizedXmlHash $currentXml
        }

        $previousState = $null
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            $previousState = Get-Content -LiteralPath $statePath -Raw |
                ConvertFrom-Json
        }

        if ($currentHash -and
            (-not $previousState -or
             $currentHash -ne $previousState.configuration_hash)) {
            throw 'Ya existe otra configuracion de Acceso asignado o fue modificada. No se reemplazo para evitar afectar politicas existentes.'
        }

        if ($ValidateOnly) {
            return
        }

        New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
        Set-AssignedAccessConfiguration $configuration

        $savedState = [ordered]@{
            profile_id = $profileId
            student_account = $StudentAccount
            configuration_hash = $newHash
        }
        $savedState | ConvertTo-Json |
            Set-Content -LiteralPath $statePath -Encoding UTF8
        $stateAcl = [System.Security.AccessControl.FileSecurity]::new()
        $stateAcl.SetAccessRuleProtection($true, $false)
        foreach ($sidText in @('S-1-5-18', 'S-1-5-32-544')) {
            $sid = [System.Security.Principal.SecurityIdentifier]::new(
                $sidText
            )
            $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
                $sid,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                [System.Security.AccessControl.AccessControlType]::Allow
            )
            $stateAcl.AddAccessRule($rule)
        }
        Set-Acl -LiteralPath $statePath -AclObject $stateAcl

        $updated = Get-AssignedAccessInstance
        $updatedXml = [System.Net.WebUtility]::HtmlDecode(
            [string]$updated.Configuration
        )
        if ((Get-NormalizedXmlHash $updatedXml) -ne $newHash) {
            throw 'Windows no confirmo la configuracion de Acceso asignado.'
        }
        return
    }

    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return
    }

    $savedState = Get-Content -LiteralPath $statePath -Raw |
        ConvertFrom-Json
    if ($savedState.profile_id -ne $profileId) {
        throw 'El archivo de estado no corresponde a LabMonitor; no se modifico Acceso asignado.'
    }

    $instance = Get-AssignedAccessInstance
    $currentConfiguration = [string]$instance.Configuration
    if ([string]::IsNullOrWhiteSpace($currentConfiguration)) {
        Remove-Item -LiteralPath $statePath -Force
        return
    }

    $currentXml = [System.Net.WebUtility]::HtmlDecode($currentConfiguration)
    if ((Get-NormalizedXmlHash $currentXml) -ne
        $savedState.configuration_hash) {
        throw 'La configuracion de Acceso asignado cambio desde la instalacion. No se elimino para preservar los cambios administrativos.'
    }

    Set-AssignedAccessConfiguration ''
    $remaining = [string](Get-AssignedAccessInstance).Configuration
    if (-not [string]::IsNullOrWhiteSpace($remaining)) {
        throw 'Windows no confirmo la eliminacion de Acceso asignado.'
    }
    Remove-Item -LiteralPath $statePath -Force
}

function Write-OperationResult([bool]$Success, [string]$Message) {
    if ([string]::IsNullOrWhiteSpace($ResultPath)) {
        return
    }
    [ordered]@{
        success = $Success
        message = $Message
    } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath -Encoding UTF8
}

if ($ValidateOnly) {
    $null = New-AssignedAccessXml
    if ($CheckRequirements) {
        Test-RequiredWindowsAccount
    }
    Write-Output 'Configuracion XML valida; no se aplicaron cambios a Windows.'
    exit 0
}

if (-not $RunAsSystem) {
    if ($Operation -eq 'Apply' -and
        ($StudentAccount -notmatch '^[A-Za-z0-9_.-]{1,20}$' -or
         $StudentAccount -eq '.' -or $StudentAccount -eq '..')) {
        throw 'El nombre debe ser una cuenta local valida de hasta 20 caracteres.'
    }

    New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
    $resultFile = Join-Path $stateDirectory (
        'assigned-access-result-' + [guid]::NewGuid().ToString('N') + '.json'
    )
    $taskName = 'LabMonitorAssignedAccess-' +
        [guid]::NewGuid().ToString('N')
    $powershellPath = Join-Path $env:SystemRoot `
        'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass ' +
        "-File `"$PSCommandPath`" -RunAsSystem -Operation $Operation " +
        "-StudentAccount `"$StudentAccount`" " +
        "-StudentExePath `"$StudentExePath`" " +
        "-ResultPath `"$resultFile`""
    $action = New-ScheduledTaskAction `
        -Execute $powershellPath `
        -Argument $arguments
    $principal = New-ScheduledTaskPrincipal `
        -UserId 'SYSTEM' `
        -LogonType ServiceAccount `
        -RunLevel Highest

    try {
        Register-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Principal $principal `
            -Force | Out-Null
        Start-ScheduledTask -TaskName $taskName

        $deadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $deadline -and
            -not (Test-Path -LiteralPath $resultFile -PathType Leaf)) {
            Start-Sleep -Milliseconds 250
        }

        if (-not (Test-Path -LiteralPath $resultFile -PathType Leaf)) {
            throw 'La tarea de Windows SYSTEM no termino en 60 segundos.'
        }

        $result = Get-Content -LiteralPath $resultFile -Raw |
            ConvertFrom-Json
        if (-not $result.success) {
            throw $result.message
        }
        Write-Output $result.message
    } finally {
        $registeredTask = Get-ScheduledTask -TaskName $taskName `
            -ErrorAction Ignore
        if ($registeredTask) {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        }
        if (Test-Path -LiteralPath $resultFile -PathType Leaf) {
            Remove-Item -LiteralPath $resultFile -Force
        }
    }
    exit 0
}

if (-not [System.Security.Principal.WindowsIdentity]::GetCurrent().IsSystem) {
    throw 'La operacion debe ejecutarse como LocalSystem.'
}

try {
    Invoke-SystemOperation
    Write-OperationResult $true 'Acceso asignado quedo configurado correctamente.'
    if ([string]::IsNullOrWhiteSpace($ResultPath)) {
        Write-Output 'Acceso asignado quedó configurado correctamente.'
    }
    exit 0
} catch {
    $errorMessage = $_.Exception.Message
    Write-OperationResult $false $_.Exception.Message
    if ([string]::IsNullOrWhiteSpace($ResultPath)) {
        [Console]::Error.WriteLine(
            "Error al configurar Acceso asignado: $errorMessage"
        )
    }
    exit 1
}
