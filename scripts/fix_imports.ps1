# PowerShell script to fix all import paths for the clean src/ structure
# This script adds src. prefix to all internal imports

Write-Host "🔧 Starting import path fixes for clean src/ structure..." -ForegroundColor Green

$replacements = @{
    'from core\.' = 'from src.core.'
    'import core\.' = 'import src.core.'
    'from utils\.' = 'from src.utils.'
    'import utils\.' = 'import src.utils.'
    'from config\.' = 'from src.config.'
    'import config\.' = 'import src.config.'
    'from api\.' = 'from src.api.'
    'import api\.' = 'import src.api.'
    'from data\.' = 'from src.data.'
    'import data\.' = 'import src.data.'
    'from legacy\.' = 'from src.legacy.'
    'import legacy\.' = 'import src.legacy.'
}

$filePatterns = @(
    "*.py"
)

$totalFixed = 0

foreach ($pattern in $filePatterns) {
    $files = Get-ChildItem -Path ".\src" -Filter $pattern -Recurse | Where-Object { 
        $_.FullName -notlike "*venv*" -and 
        $_.FullName -notlike "*__pycache__*" -and
        $_.FullName -notlike "*node_modules*" -and
        $_.FullName -notlike "*.git*"
    }
    
    foreach ($file in $files) {
        $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
        if (-not $content) { continue }
        
        $originalContent = $content
        
        foreach ($oldPattern in $replacements.Keys) {
            $newPattern = $replacements[$oldPattern]
            $content = $content -replace $oldPattern, $newPattern
        }
        
        if ($content -ne $originalContent) {
            Set-Content -Path $file.FullName -Value $content -NoNewline
            Write-Host "✅ Fixed imports in: $($file.FullName)" -ForegroundColor Cyan
            $totalFixed++
        }
    }
}

Write-Host "🎉 Import fixing complete! Fixed $totalFixed files." -ForegroundColor Green
