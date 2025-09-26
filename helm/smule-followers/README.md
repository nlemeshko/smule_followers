# Smule Followers Bot - Helm Chart

Этот Helm чарт разворачивает Smule Followers Bot в Kubernetes кластере.

## Предварительные требования

- Kubernetes 1.19+
- Helm 3.0+
- PersistentVolume для хранения данных

## Установка

### 1. Подготовка переменных окружения

Скопируйте файл с примером конфигурации:

```bash
cp values-example.yaml values.yaml
```

Отредактируйте `values.yaml` и заполните обязательные переменные:

```yaml
env:
  TELEGRAM_TOKEN: "YOUR_TELEGRAM_BOT_TOKEN_HERE"
  CHAT_ID: "YOUR_TELEGRAM_CHAT_ID_HERE"
  SMULE_ACCOUNT_IDS: "96242367,3150102762"
```

### 2. Установка чарта

```bash
# Добавьте репозиторий (если необходимо)
helm repo add smule-followers ./helm/smule-followers

# Установите чарт
helm install smule-followers ./helm/smule-followers -f ./helm/smule-followers/values.yaml
```

### 3. Проверка установки

```bash
# Проверьте статус подов
kubectl get pods -l app.kubernetes.io/name=smule-followers

# Проверьте логи
kubectl logs -l app.kubernetes.io/name=smule-followers

# Проверьте PersistentVolumeClaim
kubectl get pvc -l app.kubernetes.io/name=smule-followers
```

## Конфигурация

### Обязательные переменные окружения

- `TELEGRAM_TOKEN` - токен Telegram бота
- `CHAT_ID` - ID чата для отправки уведомлений
- `SMULE_ACCOUNT_IDS` - ID аккаунтов Smule для мониторинга (через запятую)

### Опциональные переменные

- `CHECK_INTERVAL` - интервал проверки в секундах (по умолчанию 300)
- `LOG_LEVEL` - уровень логирования (по умолчанию INFO)
- `DATA_DIR` - директория для хранения данных (по умолчанию /data)
- `TZ` - часовой пояс (по умолчанию Europe/Kyiv)

### PersistentVolume

Чарт создает PersistentVolumeClaim размером 1GB для хранения данных бота. Убедитесь, что в кластере доступен StorageClass или используйте default.

## Обновление

```bash
helm upgrade smule-followers ./helm/smule-followers -f ./helm/smule-followers/values.yaml
```

## Удаление

```bash
helm uninstall smule-followers
```

**Внимание:** При удалении PersistentVolumeClaim также будет удален, что приведет к потере данных. Если нужно сохранить данные, сделайте бэкап перед удалением.

## Безопасность

Чарт настроен с учетом лучших практик безопасности:

- Запуск от непривилегированного пользователя (UID 10001)
- Read-only root filesystem
- Отключение privilege escalation
- Ограничение ресурсов

## Мониторинг

Бот отправляет уведомления в Telegram при:
- Новых подписчиках
- Отписках
- Ошибках в работе

## Troubleshooting

### Проверка логов

```bash
kubectl logs -l app.kubernetes.io/name=smule-followers -f
```

### Проверка переменных окружения

```bash
kubectl describe pod -l app.kubernetes.io/name=smule-followers
```

### Проверка PersistentVolume

```bash
kubectl get pvc -l app.kubernetes.io/name=smule-followers
kubectl describe pvc -l app.kubernetes.io/name=smule-followers
```
