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

## Если Smule возвращает HTTP 403 / Cloudflare

`Just a moment...` вместо JSON означает, что Cloudflare требует проверку браузера.
Это не пустой список подписчиков. `cookie_configured=no` означает, что `SMULE_COOKIE`
не задан, но само по себе не доказывает причину блокировки.

Бот прекращает запросы ко всем аккаунтам при блокировке и сохраняет предыдущий
полный снимок подписчиков. Пауза по умолчанию составляет 15 минут, при повторных
блокировках — 30 и 60 минут. Заголовок `Retry-After` может увеличить эту паузу.
Сообщение о блокировке и длительности паузы записывается только в логи контейнера,
без уведомления в Telegram.
Обычный `CHECK_INTERVAL` также продолжает действовать: используется более длинное
ожидание. Успешная проверка всех аккаунтов сбрасывает увеличение паузы.
Перезапуск процесса сбрасывает паузу; не перезапускайте бот многократно при блокировке.

Дополнительные переменные в Secret, указанном в `existingSecret.name` (по умолчанию `env`):

```dotenv
SMULE_REQUEST_DELAY=3
SMULE_BLOCK_COOLDOWN=900
SMULE_COOKIE=
```

`SMULE_REQUEST_DELAY` задаёт минимальный интервал между запросами в секундах.
`SMULE_BLOCK_COOLDOWN` задаёт начальную паузу после блокировки (минимум 60 секунд).
`SMULE_COOKIE` уже поддерживается ботом и принимает строку Cookie header. Если
используете собственную действующую сессию Smule, храните cookies в Secret; не
публикуйте их в логах или Git. Cookies не гарантируют прохождение проверки Cloudflare.

Текущий Deployment получает переменные через `envFrom` из существующего Secret:
добавление этих значений только в секцию `env` файла values.yaml их в Pod не передаст.
После обновления Secret перезапустите Deployment, чтобы он получил новые значения.
Для применения изменений Python необходимо также собрать и развернуть новый образ.
При постоянной блокировке проверьте доступ к Smule из сети, где запущен бот;
описанные паузы сами по себе не снимают ограничение на стороне Smule/Cloudflare.

HTTP-логи `httpx` и `httpcore` ограничены уровнем WARNING, чтобы обычные запросы
Telegram не выводили токен в URL. Если токен уже попал в опубликованный лог,
перевыпустите его через BotFather и обновите `TELEGRAM_TOKEN` в Secret.

Определение Challenge Page описано в
[документации Cloudflare](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/).

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
