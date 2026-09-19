Write-Host "======================================================" -ForegroundColor Cyan
Write-Host " 🚀 Agentic CFO - Kubernetes Deployment Script (PowerShell)" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan

# 1. Check prerequisite tools
if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    Write-Host "❌ 'kubectl' bulunamadı. Lütfen yükleyin." -ForegroundColor Red
    Exit 1
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "❌ 'docker' bulunamadı. Lütfen yükleyin." -ForegroundColor Red
    Exit 1
}

# 2. Build local docker images
Write-Host "📦 [1/4] Docker imajları inşa ediliyor..." -ForegroundColor Yellow
docker build -t agentic-cfo-backend:latest ./backend
docker build -t agentic-cfo-frontend:latest ./frontend

# 3. Apply manifests
Write-Host "🌐 [2/4] Namespace ve Konfigürasyonlar uygulanıyor..." -ForegroundColor Yellow
kubectl apply -k k8s/

Write-Host "⏳ Pod durumları listeleniyor..." -ForegroundColor Yellow
kubectl get pods -n aicfo

Write-Host ""
Write-Host "✅ Kubernetes dağıtımı tamamlandı!" -ForegroundColor Green
Write-Host "Podları izlemek için: kubectl get pods -n aicfo -w" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
