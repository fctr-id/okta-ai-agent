# docker-publish.ps1
param(
    [Parameter()]
    [string]$Version = "",
    [Parameter()]
    [string]$Registry = "fctrid",
    [Parameter()]
    [string]$ImageName = "ai-agent-for-okta"
)

$ErrorActionPreference = "Stop"

# Always ask for version if not provided or empty
if ([string]::IsNullOrEmpty($Version)) {
    # Keep asking until a valid version is provided
    do {
        $Version = Read-Host "Enter version number (format: x.y.z or x.y.z-beta.n)"
        # Updated regex to allow semantic versioning with pre-release tags
        if (![string]::IsNullOrEmpty($Version) -and $Version -match '^\d+\.\d+\.\d+(?:-(?:beta|alpha|rc)(?:\.\d+)?)?$') {
            break
        }
        Write-Host "Invalid version format. Please use format: x.y.z (e.g., 1.0.0) or x.y.z-beta (e.g., 1.0.0-beta, 1.0.0-beta.1)" -ForegroundColor Yellow
    } while ($true)
}

# Ask if this should also be tagged as 'latest'
$tagAsLatest = Read-Host "Tag this version as 'latest' as well? (y/n)"
$latestTag = $tagAsLatest -eq "y"

Write-Host "========================================="
Write-Host "Docker Multi-Architecture Build Script"
Write-Host "Image: $Registry/$ImageName"
Write-Host "Version: $Version"
if ($latestTag) {
    Write-Host "Tags: $Version, latest"
} else {
    Write-Host "Tags: $Version"
}
Write-Host "Platforms: linux/amd64, linux/arm64"
Write-Host "========================================="

# Check if Docker is running
try {
    docker info | Out-Null
} catch {
    Write-Error "Docker is not running or not installed. Please start Docker Desktop."
    exit 1
}

# Get parent directory for context
$contextPath = (Get-Item -Path "../").FullName

# Inject version number into AppLayout.vue footer
$footerPath = Join-Path $contextPath "src/frontend/src/components/layout/AppLayout.vue"
Write-Host "Injecting version $Version into AppLayout.vue..."

if (Test-Path $footerPath) {
    # Read the current footer content
    $footerContent = Get-Content $footerPath -Raw
    
    # Backup the original file
    $backupPath = "$footerPath.backup"
    Copy-Item $footerPath $backupPath -Force
    
    # Replace the entire version-tag span content with the new version
    # This matches: <span class="version-tag">(...anything...)</span>
    $footerContent = $footerContent -replace '<span class="version-tag">\([^)]+\)</span>', "<span class=`"version-tag`">(v$Version)</span>"
    
    # Write the modified content back
    Set-Content -Path $footerPath -Value $footerContent -NoNewline
    
    Write-Host "Version injected successfully. Original backed up to AppLayout.vue.backup" -ForegroundColor Green
} else {
    Write-Warning "AppLayout.vue not found at $footerPath. Continuing without version injection."
}

# Build multi-architecture images (but don't push yet)
Write-Host "Building multi-architecture Docker images (linux/amd64, linux/arm64)..."
if ($latestTag) {
    Write-Host "Tags: $Registry/$ImageName`:$Version, $Registry/$ImageName`:latest"
} else {
    Write-Host "Tags: $Registry/$ImageName`:$Version"
}

# Build multi-architecture images using buildx
if ($latestTag) {
    docker buildx build --pull --rm `
        --platform linux/amd64,linux/arm64 `
        --file "../Dockerfile" `
        --tag "$Registry/$ImageName`:$Version" `
        --tag "$Registry/$ImageName`:latest" `
        --push `
        $contextPath
} else {
    docker buildx build --pull --rm `
        --platform linux/amd64,linux/arm64 `
        --file "../Dockerfile" `
        --tag "$Registry/$ImageName`:$Version" `
        --push `
        $contextPath
}
    
if ($LASTEXITCODE -ne 0) {
    Write-Error "Multi-architecture build failed with exit code $LASTEXITCODE"
    
    # Restore original AppLayout.vue on failure
    if (Test-Path $backupPath) {
        Move-Item $backupPath $footerPath -Force
        Write-Host "Restored original AppLayout.vue after build failure" -ForegroundColor Yellow
    }
    
    exit $LASTEXITCODE
}

Write-Host "Multi-architecture images built successfully."

# Restore original AppLayout.vue after successful build
if (Test-Path $backupPath) {
    Move-Item $backupPath $footerPath -Force
    Write-Host "Restored original AppLayout.vue" -ForegroundColor Green
}

# Ask user if they want to keep them published
$pushConfirm = Read-Host "Images were built and pushed to registry (buildx requirement). Keep them published? (y/n)"
if ($pushConfirm -ne "y") {
    Write-Host "Note: You'll need to manually remove tags from Docker Hub if desired:"
    Write-Host "Go to: https://hub.docker.com/r/$Registry/$ImageName/tags"
    exit 0
}
    
Write-Host "=========== Success ============"
if ($latestTag) {
    Write-Host "Multi-architecture images successfully published:"
    Write-Host "- $Registry/$ImageName`:$Version (linux/amd64, linux/arm64)"
    Write-Host "- $Registry/$ImageName`:latest (linux/amd64, linux/arm64)"
} else {
    Write-Host "Multi-architecture image successfully published:"
    Write-Host "- $Registry/$ImageName`:$Version (linux/amd64, linux/arm64)"
}
Write-Host "================================="