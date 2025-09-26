# Настройка regcred секрета для GitHub Container Registry

## Создание Personal Access Token

1. Перейдите в GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Нажмите "Generate new token (classic)"
3. Выберите следующие права:
   - `write:packages` - для загрузки пакетов
   - `read:packages` - для чтения пакетов
   - `delete:packages` - для удаления пакетов (опционально)
4. Скопируйте созданный токен

## Создание regcred секрета

### Вариант 1: Через kubectl
```bash
kubectl create secret docker-registry regcred \
  --docker-server=ghcr.io \
  --docker-username=YOUR_GITHUB_USERNAME \
  --docker-password=YOUR_GITHUB_TOKEN \
  --docker-email=YOUR_EMAIL \
  -n smule-followers
```

### Вариант 2: Через YAML файл
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: regcred
  namespace: smule-followers
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: <base64-encoded-docker-config>
```

Где `<base64-encoded-docker-config>` это base64 кодированный JSON:
```json
{
  "auths": {
    "ghcr.io": {
      "username": "YOUR_GITHUB_USERNAME",
      "password": "YOUR_GITHUB_TOKEN",
      "auth": "base64(username:password)"
    }
  }
}
```

### Вариант 3: Автоматическое создание
```bash
# Создайте .dockerconfigjson файл
cat > dockerconfig.json << EOF
{
  "auths": {
    "ghcr.io": {
      "username": "YOUR_GITHUB_USERNAME",
      "password": "YOUR_GITHUB_TOKEN",
      "auth": "$(echo -n 'YOUR_GITHUB_USERNAME:YOUR_GITHUB_TOKEN' | base64)"
    }
  }
}
EOF

# Создайте секрет
kubectl create secret generic regcred \
  --from-file=.dockerconfigjson=dockerconfig.json \
  --type=kubernetes.io/dockerconfigjson \
  -n smule-followers

# Удалите временный файл
rm dockerconfig.json
```

## Проверка секрета

```bash
# Проверьте существование секрета
kubectl get secret regcred -n smule-followers

# Проверьте содержимое секрета
kubectl get secret regcred -n smule-followers -o yaml
```

## Troubleshooting

### Проблема: ImagePullBackOff
```
Failed to pull image "ghcr.io/username/repo:tag": 
rpc error: code = Unknown desc = failed to resolve reference "ghcr.io/username/repo:tag": 
failed to authorize: failed to fetch anonymous token: unexpected status from GET request to https://ghcr.io/token?scope=repository%3Ausername%2Frepo%3Apull&service=ghcr.io: 401 Unauthorized
```

**Решение:** Проверьте правильность regcred секрета:
```bash
kubectl get secret regcred -n smule-followers -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq
```

### Проблема: Secret not found
```
Error: secret "regcred" not found
```

**Решение:** Создайте секрет одним из способов выше.

### Проблема: Invalid credentials
```
Error: authentication required
```

**Решение:** 
1. Проверьте правильность username и token
2. Убедитесь, что токен имеет права на чтение пакетов
3. Проверьте, что образ существует в репозитории
