# docker-publish.ps1
param(
    [Parameter()]
    [string]$Version = "0.2.0",
    [Parameter()]
    [string]$Registry = "fctrid",
    [Parameter()]
    [string]$ImageName = "ai-agent-for-okta"
)

$ErrorActionPreference = "Stop"

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

# Tag as latest
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

# Push both tags
Write-Host "Pushing image with version tag: $Registry/$ImageName`:$Version"
docker push "$Registry/$ImageName`:$Version"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to push versioned image."
    exit $LASTEXITCODE
}

Write-Host "Pushing image with latest tag: $Registry/$ImageName`:latest"
docker push "$Registry/$ImageName`:latest"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to push latest image."
    exit $LASTEXITCODE
}

# Create VERSION.md in the parent directory
$versionFile = Join-Path -Path $contextPath -ChildPath "VERSION.md"
$versionContent = "# Version History`r`n`r`n## Current Latest: v$Version ($(Get-Date -Format 'yyyy-MM-dd'))"
$versionContent | Out-File -FilePath $versionFile -Encoding utf8

Write-Host "=========== Success ============"
Write-Host "Images successfully published:"
Write-Host "- $Registry/$ImageName`:$Version"
Write-Host "- $Registry/$ImageName`:latest"
Write-Host "Version file created at: $versionFile"
Write-Host "================================="