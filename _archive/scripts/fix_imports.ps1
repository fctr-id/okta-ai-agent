# PowerShell script to fix all import paths in the restructured codebase
# This script replaces old imports with the new clean src/* structure

Write-Host "🔧 Starting import path fixes for clean src/ structure..." -ForegroundColor Green

$replacements = @{
    'config\.settings' = 'src.config.settings'
    'core\.models\.model_picker' = 'src.core.models.model_picker'
    'legacy\.sql_mode\.' = 'src.legacy.sql_mode.'
    'legacy\.realtime_mode\.' = 'src.legacy.realtime_mode.'
    'core\.okta\.sync\.operations' = 'src.core.okta.sync.operations'
    'core\.okta\.sync\.models' = 'src.core.okta.sync.models'
    'core\.okta\.client\.client' = 'src.core.okta.client.client'
    'core\.security\.' = 'src.core.security.'
    'core\.agents\.' = 'src.core.agents.'
    'core\.orchestration\.' = 'src.core.orchestration.'
    'utils\.' = 'src.utils.'
    'api\.main' = 'src.api.main'
    'api\.routers\.' = 'src.api.routers.'
    'data\.schemas\.' = 'src.data.schemas.'
}

$filePatterns = @(
    "*.py"
    "Dockerfile"
    "docker-compose.yml"
)

foreach ($pattern in $filePatterns) {
    $files = Get-ChildItem -Path . -Filter $pattern -Recurse | Where-Object { $_.FullName -notlike "*__pycache__*" }
    
    foreach ($file in $files) {
        $content = Get-Content $file.FullName -Raw
        $originalContent = $content
        
        foreach ($oldPattern in $replacements.Keys) {
            $newPattern = $replacements[$oldPattern]
            $content = $content -replace $oldPattern, $newPattern
        }
        
        if ($content -ne $originalContent) {
            Set-Content -Path $file.FullName -Value $content -NoNewline
            Write-Host "✅ Fixed imports in: $($file.FullName)" -ForegroundColor Cyan
        }
    }
}

Write-Host "🎉 Import fixing complete!" -ForegroundColor Green
