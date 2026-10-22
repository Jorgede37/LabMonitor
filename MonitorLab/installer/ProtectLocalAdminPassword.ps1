[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$entropy = [System.Text.Encoding]::UTF8.GetBytes(
    'LabMonitor.LocalAdmin.v1'
)

try {
    Add-Type -AssemblyName System.Security
    $password = [System.IO.File]::ReadAllText($InputPath)
    if ([string]::IsNullOrWhiteSpace($password)) {
        throw 'La contraseña local está vacía.'
    }

    $plainBytes = [System.Text.Encoding]::UTF8.GetBytes($password)
    $protectedBytes = $null
    try {
        $protectedBytes = [System.Security.Cryptography.ProtectedData]::Protect(
            $plainBytes,
            $entropy,
            [System.Security.Cryptography.DataProtectionScope]::LocalMachine
        )
        $protectedText = [Convert]::ToBase64String($protectedBytes)
        [System.IO.File]::WriteAllText(
            $OutputPath,
            $protectedText,
            [System.Text.Encoding]::ASCII
        )
    } finally {
        [Array]::Clear($plainBytes, 0, $plainBytes.Length)
        if ($null -ne $protectedBytes) {
            [Array]::Clear($protectedBytes, 0, $protectedBytes.Length)
        }
    }
} finally {
    if (Test-Path -LiteralPath $InputPath) {
        Remove-Item -LiteralPath $InputPath -Force
    }
}
