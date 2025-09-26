# Развертывание Smule Followers Bot

## Быстрый старт

### 1. Подготовка переменных окружения

Создайте файл с переменными окружения:

```bash
# Для локальной разработки
cp env.example .env
# Отредактируйте .env и заполните ваши значения

# Для Kubernetes
cp helm/smule-followers/values-example.yaml helm/smule-followers/values.yaml
# Отредактируйте values.yaml и заполните ваши значения
```

### 2. Обязательные переменные

```bash
# Telegram Bot Token (получите у @BotFather)
TELEGRAM_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# ID чата для уведомлений (получите у @userinfobot)
CHAT_ID=-1001234567890

# ID аккаунтов Smule для мониторинга (через запятую)
SMULE_ACCOUNT_IDS=96242367,3150102762
```

### 3. Локальный запуск

```bash
# Установите зависимости
pip install -r requirements.txt

# Запустите бота
python smule_bot.py
```

### 4. Запуск в Kubernetes

```bash
# Установите Helm чарт
helm install smule-followers ./helm/smule-followers -f ./helm/smule-followers/values.yaml

# Проверьте статус
kubectl get pods -l app.kubernetes.io/name=smule-followers

# Посмотрите логи
kubectl logs -l app.kubernetes.io/name=smule-followers -f
```

### 5. Обновление

```bash
# Обновите конфигурацию в values.yaml, затем:
helm upgrade smule-followers ./helm/smule-followers -f ./helm/smule-followers/values.yaml
```

### 6. Удаление

```bash
helm uninstall smule-followers
```

## Особенности

- **PersistentVolume**: 1GB для хранения данных о подписчиках
- **Безопасность**: Запуск от непривилегированного пользователя
- **Мониторинг**: Автоматические уведомления в Telegram
- **Rate Limiting**: Контроль частоты запросов к API

## Troubleshooting

### Проблемы с переменными окружения

```bash
# Проверьте ConfigMap
kubectl get configmap -l app.kubernetes.io/name=smule-followers

# Проверьте Secret
kubectl get secret -l app.kubernetes.io/name=smule-followers
```

### Проблемы с PersistentVolume

```bash
# Проверьте PVC
kubectl get pvc -l app.kubernetes.io/name=smule-followers

# Проверьте доступные StorageClass
kubectl get storageclass
```

### Проблемы с сетью

```bash
# Проверьте логи на ошибки сети
kubectl logs -l app.kubernetes.io/name=smule-followers | grep -i "error\|network\|connection"
```
