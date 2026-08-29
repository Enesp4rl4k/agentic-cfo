#!/usr/bin/env bash
set -euo pipefail

echo "======================================================"
echo " 🚀 Agentic CFO - Kubernetes Deployment Script (Linux/Mac)"
echo "======================================================"

# 1. Check prerequisite tools
command -v kubectl >/dev/null 2>&1 || { echo "❌ 'kubectl' bulunamadı. Lütfen yükleyin."; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "❌ 'docker' bulunamadı. Lütfen yükleyin."; exit 1; }

# 2. Build local docker images
echo "📦 [1/4] Docker imajları inşa ediliyor..."
docker build -t agentic-cfo-backend:latest ./backend
docker build -t agentic-cfo-frontend:latest ./frontend

# 3. Create Namespace if not exists
echo "🌐 [2/4] Kubernetes Namespace ve Konfigürasyonları uygulanıyor..."
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-config.yaml
kubectl apply -f k8s/02-secrets.yaml

# 4. Deploy Databases
echo "🗄️ [3/4] Postgres ve Redis başlatılıyor..."
kubectl apply -f k8s/10-postgres.yaml
kubectl apply -f k8s/11-redis.yaml

echo "⏳ Veritabanının hazır olması bekleniyor..."
kubectl wait --namespace aicfo --for=condition=ready pod -l app=postgres --timeout=120s || true

# 5. Apply Database Migrations & Deploy Applications
echo "🚀 [4/4] DB Migration ve Uygulama podları devreye alınıyor..."
kubectl apply -f k8s/05-migration-job.yaml
kubectl apply -f k8s/20-backend.yaml
kubectl apply -f k8s/21-worker.yaml
kubectl apply -f k8s/22-worker-maintenance.yaml
kubectl apply -f k8s/23-hpa-backend.yaml
kubectl apply -f k8s/30-frontend.yaml
kubectl apply -f k8s/40-ingress.yaml

echo ""
echo "✅ Tüm servisler başarıyla dağıtıldı!"
echo "Pod durumlarını kontrol etmek için:"
echo "👉 kubectl get pods -n aicfo"
echo "======================================================"
