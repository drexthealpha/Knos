<#
.SYNOPSIS
A local Solana validator with the devnet-deployed programs Knos composes: the Solana Attestation Service and
Lighthouse. SPL Token, ATA and Memo are already in the validator's genesis. Tests and the bench run here, because
devnet airdrops are rate-limited; the recorded demo runs on devnet.

    scripts\devchain.ps1 start    # clone both programs from devnet, start on 127.0.0.1:8899, wait until healthy
    scripts\devchain.ps1 stop
    scripts\devchain.ps1 status

Needs the Solana CLI (Anza installer). Set KNOS_DEVCHAIN_DIR to move the ledger (default ~/.knos-devchain).
#>

param(
    [ValidateSet("start", "stop", "status")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"

$SAS = "22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG"
$LIGHTHOUSE = "L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95"

$DefaultDir = Join-Path $HOME ".knos-devchain"
$Dir = if ($env:KNOS_DEVCHAIN_DIR) { $env:KNOS_DEVCHAIN_DIR } else { $DefaultDir }
$Url = "http://127.0.0.1:8899"
$PidFile = Join-Path $Dir "pid"
$LogFile = Join-Path $Dir "validator.log"
$LedgerDir = Join-Path $Dir "ledger"

# Add Solana release bin to PATH if present
$SolanaBin = Join-Path $HOME ".local\share\solana\install\active_release\bin"
if (Test-Path $SolanaBin) {
    $env:PATH = "$SolanaBin;$env:PATH"
}

function Test-Healthy {
    try {
        $body = '{"jsonrpc":"2.0","id":1,"method":"getHealth"}'
        $response = Invoke-RestMethod -Uri $Url -Method Post -Body $body -ContentType "application/json" -TimeoutSec 2 -ErrorAction SilentlyContinue
        return ($response.result -eq "ok")
    } catch {
        return $false
    }
}

switch ($Action) {
    "start" {
        if (Test-Healthy) {
            Write-Host "devchain already running at $Url"
            exit 0
        }
        if (-not (Test-Path $Dir)) {
            New-Item -ItemType Directory -Path $Dir -Force | Out-Null
        }

        $validatorArgs = @(
            "--reset",
            "--quiet",
            "--ledger", $LedgerDir,
            "--limit-ledger-size", "10000",
            "--clone-upgradeable-program", $SAS,
            "--clone-upgradeable-program", $LIGHTHOUSE,
            "--url", "devnet"
        )

        $proc = Start-Process -FilePath "solana-test-validator" -ArgumentList $validatorArgs `
            -RedirectStandardOutput $LogFile -RedirectStandardError $LogFile -PassThru -NoNewWindow

        Set-Content -Path $PidFile -Value $proc.Id -Force

        for ($i = 1; $i -le 120; $i++) {
            if (Test-Healthy) {
                Write-Host "devchain up at $Url (SAS and Lighthouse cloned from devnet)"
                exit 0
            }
            if ($proc.HasExited) {
                Write-Error "validator exited; see $LogFile"
                exit 1
            }
            Start-Sleep -Seconds 1
        }
        Write-Error "validator not healthy after 120s; see $LogFile"
        exit 1
    }
    "stop" {
        if (Test-Path $PidFile) {
            try {
                $pidVal = Get-Content -Path $PidFile -ErrorAction SilentlyContinue
                if ($pidVal) {
                    Stop-Process -Id ([int]$pidVal) -Force -ErrorAction SilentlyContinue
                }
            } catch {}
            Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
        }
        Write-Host "devchain stopped"
        exit 0
    }
    "status" {
        if (Test-Healthy) {
            Write-Host "up at $Url"
            exit 0
        } else {
            Write-Host "down"
            exit 1
        }
    }
}
