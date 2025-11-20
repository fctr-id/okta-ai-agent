
$ErrorActionPreference = "Stop"

function Move-ToArchive {
    param (
        [string]$Path
    )
    if (Test-Path $Path) {
        $relativePath = $Path.Substring($PWD.Path.Length + 1)
        $destPath = Join-Path "_archive" $relativePath
        $destDir = Split-Path $destPath -Parent
        
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        
        Move-Item -Path $Path -Destination $destPath -Force
        Write-Host "Moved: $relativePath -> $destPath"
    } else {
        Write-Host "Skipping: $Path (Not found)"
    }
}

# Files to archive
Move-ToArchive (Join-Path $PWD "src\api\routers\realtime_hybrid.py")
Move-ToArchive (Join-Path $PWD "src\core\security\polars_security_NOT_USED.py")
Move-ToArchive (Join-Path $PWD "src\data\schemas\Okta_API_entitity_endpoint_reference_GET_ONLY copy.json")
Move-ToArchive (Join-Path $PWD "src\data\schemas\full_postman_collection_sfasfd.json")

Write-Host "Final cleanup complete."
