# Настройка GitHub Actions для автоматического деплоя

## Предварительные требования

### 1. GitHub Secrets
Убедитесь, что в настройках репозитория (Settings → Secrets and variables → Actions) настроены следующие секреты:

- `ACCESS_TOKEN` - Personal Access Token с правами на запись в репозиторий
- `K3S_KUBECONFIG` - kubeconfig файл вашего K3s кластера (в base64)

### 2. Создание секретов в Kubernetes
Перед первым деплоем создайте необходимые секреты в вашем кластере:

**Секрет с переменными окружения:**
```bash
kubectl create secret generic env \
  --from-literal=TELEGRAM_TOKEN="ваш_токен" \
  --from-literal=CHAT_ID="ваш_chat_id" \
  --from-literal=SMULE_ACCOUNT_IDS="96242367,3150102762" \
  --from-literal=CHECK_INTERVAL="300" \
  --from-literal=LOG_LEVEL="INFO" \
  --from-literal=DATA_DIR="/data" \
  --from-literal=TZ="Europe/Kyiv" \
  -n smule-followers
```

**Секрет для доступа к GitHub Container Registry:**
```bash
kubectl create secret docker-registry regcred \
  --docker-server=ghcr.io \
  --docker-username=YOUR_GITHUB_USERNAME \
  --docker-password=YOUR_GITHUB_TOKEN \
  --docker-email=YOUR_EMAIL \
  -n smule-followers
```

## Как работает workflow

### 1. Build Job
- Создает новый тег версии
- Собирает Docker образ для linux/amd64 и linux/arm64
- Пушит образ в GitHub Container Registry

### 2. Deploy Job (только для main ветки)
- Проверяет существование секрета `env`
- Деплоит приложение с помощью Helm
- Проверяет статус деплоя

## Триггеры

Workflow запускается при:
- Push в ветку `master`
- Ручной запуск через GitHub Actions

## Проверка деплоя

После успешного деплоя проверьте:

```bash
# Статус подов
kubectl get pods -n smule-followers -l app.kubernetes.io/name=smule-followers

# Логи приложения
kubectl logs -n smule-followers -l app.kubernetes.io/name=smule-followers -f

# Переменные окружения
kubectl exec -n smule-followers -it deployment/smule-followers -- printenv | grep -E "(TELEGRAM|CHAT|SMULE)"
```

## Troubleshooting

### Проблема: Secret not found
```
❌ Secret 'env' not found in namespace smule-followers
```
**Решение:** Создайте секрет командой выше

### Проблема: Image pull failed
```
Failed to pull image "ghcr.io/username/repo:tag"
```
**Решение:** Проверьте права доступа к GitHub Container Registry

### Проблема: Helm deployment failed
```
Error: UPGRADE FAILED: another operation (install/upgrade/rollback) is in progress
```
**Решение:** Подождите завершения предыдущей операции или выполните:
```bash
helm rollback smule-followers -n smule-followers
```

## Обновление секрета

Для обновления переменных окружения:

```bash
kubectl create secret generic env \
  --from-literal=TELEGRAM_TOKEN="новый_токен" \
  --from-literal=CHAT_ID="новый_chat_id" \
  --from-literal=SMULE_ACCOUNT_IDS="96242367,3150102762" \
  --dry-run=client -o yaml | kubectl apply -f - -n smule-followers
```

После обновления секрета перезапустите поды:
```bash
kubectl rollout restart deployment/smule-followers -n smule-followers
```
