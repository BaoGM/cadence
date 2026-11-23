param([Parameter(Mandatory)][ValidateSet('Initialize')] [string]$Action)
$ErrorActionPreference = 'Stop'
$keyName = 'Cadence.Windows.Update.v1'
$publicKey = Join-Path $PSScriptRoot '../assets/update-key.txt'
if (![System.Security.Cryptography.CngKey]::Exists($keyName)) {
    if ($Action -ne 'Initialize' -or (Test-Path -LiteralPath $publicKey)) {
        throw 'The original Cadence signing key is required.'
    }
    $options = [System.Security.Cryptography.CngKeyCreationParameters]::new()
    $options.ExportPolicy = [System.Security.Cryptography.CngExportPolicies]::AllowExport
    $size = [System.Security.Cryptography.CngProperty]::new('Length',[BitConverter]::GetBytes(3072),0)
    $options.Parameters.Add($size)
    $key = [System.Security.Cryptography.CngKey]::Create('RSA',$keyName,$options)
} else {
    $key = [System.Security.Cryptography.CngKey]::Open($keyName)
}
try {
    $pub = [Convert]::ToBase64String($key.Export([System.Security.Cryptography.CngKeyBlobFormat]::GenericPublicBlob))
    if ($Action -eq 'Initialize' -and !(Test-Path -LiteralPath $publicKey)) {
        [IO.File]::WriteAllText($publicKey,$pub,[Text.Encoding]::ASCII)
    }
    if ($pub -cne [IO.File]::ReadAllText($publicKey).Trim()) { throw 'Public key mismatch.' }
} finally { $key.Dispose() }
