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

Write-Host "========================================="
Write-Host "Docker Image Build and Publish Script"
Write-Host "Image: $Registry/$ImageName"
Write-Host "Version: $Version"
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

# Build the image with version tag - pointing to parent directory
Write-Host "Building Docker image: $Registry/$ImageName`:$Version"
Write-Host "Using Dockerfile from: $contextPath"
docker build --pull --rm -f "../Dockerfile" -t "$Registry/$ImageName`:$Version" $contextPath

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

# Always tag as latest, even for beta versions
Write-Host "Tagging as latest"
docker tag "$Registry/$ImageName`:$Version" "$Registry/$ImageName`:latest"

# Ask user if they want to push
$pushConfirm = Read-Host "Do you want to push the images to Docker registry? (y/n)"
if ($pushConfirm -ne "y") {
    Write-Host "Image push canceled."
    exit 0
}

# Check if user is logged in
$loginStatus = docker info 2>&1 | Select-String "Username"
if (!$loginStatus) {
    Write-Host "Not logged into Docker Hub. Please login:"
    docker login
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Login failed. Aborting publish."
        exit 1
    }
}

# Push versioned tag
Write-Host "Pushing image with version tag: $Registry/$ImageName`:$Version"
docker push "$Registry/$ImageName`:$Version"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to push versioned image."
    exit $LASTEXITCODE
}

# Always push latest tag
Write-Host "Pushing image with latest tag: $Registry/$ImageName`:latest"
docker push "$Registry/$ImageName`:latest"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to push latest image."
    exit $LASTEXITCODE
}

# Create VERSION.md in the parent directory with proper formatting
#$versionFile = Join-Path -Path $contextPath -ChildPath "VERSION.md"
#$releaseType = if ($Version -match '-') { "Beta" } else { "Stable" }
#$versionContent = "# Version History`r`n`r`n## Current Latest: v$Version ($releaseType, $(Get-Date -Format 'yyyy-MM-dd'))"
#$versionContent | Out-File -FilePath $versionFile -Encoding utf8

Write-Host "=========== Success ============"
Write-Host "Images successfully published:"
Write-Host "- $Registry/$ImageName`:$Version"
Write-Host "- $Registry/$ImageName`:latest"
Write-Host "Version file created at: $versionFile"
Write-Host "================================="