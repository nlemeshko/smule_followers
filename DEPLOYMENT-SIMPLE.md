# Простое развертывание Smule Followers Bot

## Предварительные требования

1. **Создайте секрет с переменными окружения**:
```bash
kubectl create secret generic env \
  --from-literal=TELEGRAM_TOKEN="ваш_токен" \
  --from-literal=CHAT_ID="ваш_chat_id" \
  --from-literal=SMULE_ACCOUNT_IDS="96242367,3150102762" \
  --from-literal=CHECK_INTERVAL="300" \
  --from-literal=LOG_LEVEL="INFO" \
  --from-literal=DATA_DIR="/data" \
  --from-literal=TZ="Europe/Kyiv"
```

2. **Создайте секрет для доступа к GitHub Container Registry**:
```bash
kubectl create secret docker-registry regcred \
  --docker-server=ghcr.io \
  --docker-username=YOUR_GITHUB_USERNAME \
  --docker-password=YOUR_GITHUB_TOKEN \
  --docker-email=YOUR_EMAIL
```

3. **Или создайте секрет из .env файла**:
```bash
kubectl create secret generic env --from-env-file=.env
```

## Установка

### 1. Установите Helm чарт:
```bash
helm install smule-followers ./helm/smule-followers
```

### 2. Или с кастомным именем секрета:
```bash
helm install smule-followers ./helm/smule-followers \
  --set existingSecret.name="ваше_имя_секрета"
```

## Проверка

```bash
# Проверьте статус подов
kubectl get pods -l app.kubernetes.io/name=smule-followers

# Проверьте логи
kubectl logs -l app.kubernetes.io/name=smule-followers -f

# Проверьте переменные окружения в поде
kubectl exec -it deployment/smule-followers -- env | grep -E "(TELEGRAM|CHAT|SMULE)"

# Проверьте healthcheck
kubectl exec -it deployment/smule-followers -- python /app/healthcheck.py
```

## Обновление

```bash
helm upgrade smule-followers ./helm/smule-followers
```

## Удаление

```bash
helm uninstall smule-followers
```

## Управление секретом

```bash
# Посмотреть секрет
kubectl get secret env -o yaml

# Обновить секрет
kubectl create secret generic env \
  --from-literal=TELEGRAM_TOKEN="новый_токен" \
  --from-literal=CHAT_ID="новый_chat_id" \
  --from-literal=SMULE_ACCOUNT_IDS="96242367,3150102762" \
  --dry-run=client -o yaml | kubectl apply -f -

# Удалить секрет
kubectl delete secret env
```

## Troubleshooting

### Проблемы с секретом:
```bash
# Проверьте существование секрета
kubectl get secret env

# Проверьте содержимое секрета
kubectl get secret env -o jsonpath='{.data}' | jq -r 'to_entries[] | "\(.key): \(.value | @base64d)"'
```

### Проблемы с переменными окружения:
```bash
# Проверьте переменные в поде
kubectl exec -it deployment/smule-followers -- printenv | grep -E "(TELEGRAM|CHAT|SMULE)"
```
