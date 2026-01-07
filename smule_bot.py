import asyncio
import aiohttp
import json
import os
import ssl
import certifi
from telegram import Bot
from telegram.error import TelegramError, RetryAfter
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time

# ───────────────────────────────────────────────
# env + логирование
# ───────────────────────────────────────────────
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Каталог для хранения файлов (по умолчанию /app)
DATA_DIR = os.getenv("DATA_DIR", "/app")
os.makedirs(DATA_DIR, exist_ok=True)

# Алиасы для аккаунтов
ACCOUNT_ALIASES = {
    "96242367": "dsip",
    "3150102762": "lithiumly"
}


class TelegramRateLimiter:
    """Класс для контроля частоты отправки сообщений в Telegram"""
    
    def __init__(self, max_messages_per_second: float = 1.0, max_messages_per_minute: int = 20):
        self.max_messages_per_second = max_messages_per_second
        self.max_messages_per_minute = max_messages_per_minute
        self.last_send_time = 0.0
        self.message_times = []
        
    async def wait_if_needed(self):
        """Ожидание перед отправкой сообщения, если необходимо"""
        current_time = time.time()
        
        # Проверяем лимит по секундам
        time_since_last = current_time - self.last_send_time
        min_interval = 1.0 / self.max_messages_per_second
        if time_since_last < min_interval:
            wait_time = min_interval - time_since_last
            logger.info(f"Ожидание {wait_time:.2f}с для соблюдения лимита скорости")
            await asyncio.sleep(wait_time)
            current_time = time.time()
        
        # Проверяем лимит по минутам
        one_minute_ago = current_time - 60
        self.message_times = [t for t in self.message_times if t > one_minute_ago]
        
        if len(self.message_times) >= self.max_messages_per_minute:
            oldest_message = min(self.message_times)
            wait_time = oldest_message + 60 - current_time
            if wait_time > 0:
                logger.info(f"Ожидание {wait_time:.2f}с для соблюдения минутного лимита")
                await asyncio.sleep(wait_time)
                current_time = time.time()
        
        # Обновляем времена
        self.last_send_time = current_time
        self.message_times.append(current_time)


class SmuleFollowersBot:
    def __init__(self, telegram_token: str, chat_id: str, account_ids):
        self.bot = Bot(token=telegram_token)
        self.chat_id = chat_id
        self.account_ids = account_ids if isinstance(account_ids, list) else [account_ids]
        self.rate_limiter = TelegramRateLimiter()

        # Заголовки к Smule API
        self.headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/123.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Connection": "keep-alive",
        }

        # Известные подписчики и кэш метаданных
        self.known_followers: dict[str, set[str]] = {}
        self.followers_meta: dict[str, dict[str, dict]] = {}

        for account_id in self.account_ids:
            self.known_followers[account_id] = self._load_followers_set(account_id)
            self.followers_meta[account_id] = self._load_followers_meta(account_id)

    # ───────────────────────────────────────────────
    # Работа с файлами
    # ───────────────────────────────────────────────
    def _followers_file(self, account_id: str) -> str:
        return os.path.join(DATA_DIR, f"followers_{account_id}.json")

    def _followers_meta_file(self, account_id: str) -> str:
        return os.path.join(DATA_DIR, f"followers_meta_{account_id}.json")

    def _load_followers_set(self, account_id: str) -> set:
        fp = self._followers_file(account_id)
        try:
            if os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return set(data) if isinstance(data, list) else set()
            return set()
        except Exception as e:
            logger.error(f"Ошибка при загрузке подписчиков ({account_id}): {e}")
            return set()

    def _save_followers_set(self, account_id: str) -> None:
        fp = self._followers_file(account_id)
        try:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(sorted(self.known_followers[account_id]), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка при сохранении подписчиков ({account_id}): {e}")

    def _load_followers_meta(self, account_id: str) -> dict:
        fp = self._followers_meta_file(account_id)
        try:
            if os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
            return {}
        except Exception as e:
            logger.error(f"Ошибка при загрузке метаданных подписчиков ({account_id}): {e}")
            return {}

    def _save_followers_meta(self, account_id: str) -> None:
        fp = self._followers_meta_file(account_id)
        try:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(self.followers_meta[account_id], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка при сохранении метаданных подписчиков ({account_id}): {e}")

    # ───────────────────────────────────────────────
    # HTTP-сессия с валидным CA (certifi)
    # ───────────────────────────────────────────────
    def _build_session(self) -> aiohttp.ClientSession:
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        timeout = aiohttp.ClientTimeout(total=10, connect=2, sock_read=15)
        connector = aiohttp.TCPConnector(ssl=ssl_ctx, limit=10)
        return aiohttp.ClientSession(connector=connector, timeout=timeout)

    # ───────────────────────────────────────────────
    # Smule API
    # ───────────────────────────────────────────────
    async def _get_followers_page(self, session: aiohttp.ClientSession,
                                  account_id: str, offset: int = 0, limit: int = 20) -> dict | None:
        url = "https://www.smule.com/api/profile/followers"
        params = {"accountId": account_id, "offset": offset, "limit": limit}

        try:
            logger.debug(f"Отправка запроса к API: {url}, params={params}")
            async with session.get(url, params=params, headers=self.headers) as resp:
                logger.debug(f"Получен ответ: HTTP {resp.status} для аккаунта {account_id}, offset={offset}")
                if resp.status == 200:
                    data = await resp.json()
                    logger.debug(f"Успешно получены данные для аккаунта {account_id}, offset={offset}")
                    return data
                text = await resp.text()
                logger.error(f"HTTP {resp.status} {url} {params} → {text[:300]}")
                return None
        except asyncio.TimeoutError as e:
            logger.error(f"Таймаут при запросе к API для аккаунта {account_id}, offset={offset}: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка сети ({account_id}, offset={offset}): {e}")
            return None

    async def _get_all_followers(self, session: aiohttp.ClientSession, account_id: str) -> list[dict]:
        all_followers: list[dict] = []
        offset, limit = 0, 20
        consecutive_errors = 0
        max_consecutive_errors = 3
        has_successful_page = False  # Флаг успешной загрузки хотя бы одной страницы

        while True:
            try:
                logger.debug(f"Запрос страницы подписчиков для аккаунта {account_id}, offset={offset}, limit={limit}")
                data = await self._get_followers_page(session, account_id, offset, limit)
                if not data or "list" not in data:
                    logger.warning(f"Пустой ответ от API для аккаунта {account_id}, offset={offset}, ошибок подряд: {consecutive_errors + 1}")
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error(f"Слишком много ошибок подряд для аккаунта {account_id}, прерываем загрузку")
                        # Если не было ни одной успешной страницы, это ошибка API
                        if not has_successful_page:
                            raise Exception(f"Не удалось загрузить данные для аккаунта {account_id}: API возвращает ошибки (HTTP 418)")
                        # Если были успешные страницы, но потом начались ошибки, возвращаем частичные данные
                        logger.warning(f"Возвращаем частично загруженные данные для аккаунта {account_id}: {len(all_followers)} подписчиков")
                        break
                    wait_time = 2.0 * consecutive_errors  # Увеличиваем задержку с каждой ошибкой
                    logger.info(f"Ожидание {wait_time:.1f} секунд перед повтором запроса (ошибка {consecutive_errors}/{max_consecutive_errors})")
                    await asyncio.sleep(wait_time)
                    continue

                consecutive_errors = 0  # Сбрасываем счетчик ошибок при успехе
                has_successful_page = True  # Отмечаем успешную загрузку
                batch = data["list"] or []
                
                if not batch:
                    logger.info(f"Получен пустой список подписчиков для аккаунта {account_id}")
                    break
                
                all_followers.extend(batch)
                logger.debug(f"Загружено {len(batch)} подписчиков для аккаунта {account_id}, всего: {len(all_followers)}")
                
                if len(batch) < limit:
                    logger.info(f"Завершена загрузка подписчиков для аккаунта {account_id}, всего: {len(all_followers)}")
                    break

                offset += limit
                await asyncio.sleep(0.5)
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Ошибка при загрузке страницы {offset} для аккаунта {account_id}: {e}")
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(f"Слишком много ошибок подряд для аккаунта {account_id}, прерываем загрузку")
                    # Если не было ни одной успешной страницы, это ошибка API
                    if not has_successful_page:
                        raise Exception(f"Не удалось загрузить данные для аккаунта {account_id} после {consecutive_errors} ошибок")
                    # Если были успешные страницы, возвращаем частичные данные
                    logger.warning(f"Возвращаем частично загруженные данные для аккаунта {account_id}: {len(all_followers)} подписчиков")
                    break
                
                # Увеличиваем задержку при ошибках
                wait_time = min(2.0 * consecutive_errors, 10.0)
                logger.info(f"Ожидание {wait_time} секунд перед повтором")
                await asyncio.sleep(wait_time)

        # Если не было ни одной успешной страницы и список пустой, это ошибка
        if not has_successful_page and not all_followers:
            raise Exception(f"Не удалось загрузить ни одного подписчика для аккаунта {account_id}: API возвращает ошибки")
            
        return all_followers

    # ───────────────────────────────────────────────
    # Обработка и уведомления
    # ───────────────────────────────────────────────
    @staticmethod
    def _extract_info(f: dict) -> dict:
        return {
            "account_id": str(f.get("account_id") or ""),
            "handle": f.get("handle") or "Unknown",
            "name": f.get("name") or f.get("handle") or "Unknown",
            "pic_url": f.get("pic_url") or "",
            "verified": bool(f.get("verified", False)),
            "is_vip": bool(f.get("is_vip", False)),
        }

    def _format_follow_message(self, info: dict, account_id: str) -> str:
        alias = ACCOUNT_ALIASES.get(account_id, account_id)
        lines = [
            "🎵 Новый подписчик!",
            "",
            f"📊 Аккаунт Smule: {alias}",
            f"👤 Имя: {info['name']}",
            f"📝 Ник: @{info['handle']}",
        ]
        if info["verified"]:
            lines.append("✅ Верифицированный аккаунт")
        if info["is_vip"]:
            lines.append("⭐ VIP аккаунт")
        if info["pic_url"]:
            lines.append(f"🖼 Аватар: {info['pic_url']}")
        lines.append(f"🔗 Профиль: https://www.smule.com/{info['handle']}")
        lines.append(f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return "\n".join(lines)

    def _format_unfollow_message(self, info: dict, account_id: str) -> str:
        alias = ACCOUNT_ALIASES.get(account_id, account_id)
        lines = [
            "❌ Подписчик отписался!",
            "",
            f"📊 Аккаунт Smule: {alias}",
            f"👤 Имя: {info.get('name', 'Unknown')}",
            f"📝 Ник: @{info.get('handle', 'Unknown')}",
            f"🔗 Профиль: https://www.smule.com/{info.get('handle', 'Unknown')}",
            f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        return "\n".join(lines)

    async def _send_text(self, text: str, max_retries: int = 5) -> bool:
        """Отправка текстового сообщения с улучшенной обработкой ошибок и rate limiting"""
        
        for attempt in range(max_retries):
            try:
                # Применяем rate limiting перед каждой попыткой
                await self.rate_limiter.wait_if_needed()
                
                await self.bot.send_message(chat_id=self.chat_id, text=text)
                logger.info("Уведомление отправлено в Telegram")
                return True
                
            except RetryAfter as e:
                # Telegram просит подождать определенное время
                wait_time = e.retry_after + 1  # Добавляем 1 секунду для надежности
                logger.warning(f"Rate limit от Telegram: ожидание {wait_time}с")
                await asyncio.sleep(wait_time)
                
            except TelegramError as e:
                if "429" in str(e) or "Too Many Requests" in str(e):
                    # Дополнительная обработка 429 ошибки
                    wait_time = min(60 * (attempt + 1), 300)  # Максимум 5 минут
                    logger.warning(f"429 Too Many Requests: ожидание {wait_time}с (попытка {attempt + 1})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Ошибка отправки в Telegram (попытка {attempt + 1}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка
                    
            except Exception as e:
                logger.error(f"Неожиданная ошибка при отправке сообщения (попытка {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        
        logger.error(f"Не удалось отправить сообщение после {max_retries} попыток")
        return False

    async def _send_batch_messages(self, messages: list[str]) -> None:
        """Отправка пакета сообщений с контролем скорости"""
        if not messages:
            return
            
        logger.info(f"Отправка пакета из {len(messages)} сообщений")
        
        for i, message in enumerate(messages):
            success = await self._send_text(message)
            if not success:
                logger.warning(f"Не удалось отправить сообщение {i + 1}/{len(messages)}")
            
            # Дополнительная задержка между сообщениями в пакете
            if i < len(messages) - 1:
                await asyncio.sleep(0.5)

    async def _check_account_with_retry(self, session: aiohttp.ClientSession, account_id: str, max_retries: int = 3) -> tuple[int, int]:
        """Проверка аккаунта с повторными попытками при ошибках"""
        for attempt in range(max_retries):
            try:
                logger.debug(f"Попытка {attempt + 1}/{max_retries} проверки аккаунта {account_id}")
                return await self._check_account(session, account_id)
            except Exception as e:
                logger.error(f"Ошибка при проверке аккаунта {account_id} (попытка {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    # Уменьшаем время ожидания для быстрого выхода при ошибках API
                    wait_time = 30  # 30 секунд вместо 5 минут для быстрого выхода
                    logger.info(f"Повторная попытка через {wait_time} секунд")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Не удалось проверить аккаунт {account_id} после {max_retries} попыток")
                    # Отправляем уведомление об ошибке
                    error_msg = f"❌ Ошибка при проверке аккаунта {ACCOUNT_ALIASES.get(account_id, account_id)}: {str(e)[:200]}"
                    await self._send_text(error_msg)
                    return (0, 0)
        
        return (0, 0)

    async def _check_account(self, session: aiohttp.ClientSession, account_id: str) -> tuple[int, int]:
        try:
            followers = await self._get_all_followers(session, account_id)
        except Exception as e:
            # Если не удалось загрузить данные из-за ошибок API, не обрабатываем изменения
            logger.error(f"Ошибка загрузки подписчиков для аккаунта {account_id}: {e}")
            raise  # Пробрасываем исключение выше для обработки в _check_account_with_retry
        
        if not followers:
            # Пустой список может быть нормальным (нет подписчиков), но лучше проверить
            # Если у нас уже были подписчики, а теперь список пустой, это подозрительно
            if self.known_followers.get(account_id):
                logger.warning(f"Получен пустой список подписчиков для аккаунта {account_id}, но ранее были подписчики. Возможно, ошибка API.")
                # Не обрабатываем изменения, чтобы избежать ложных уведомлений
                raise Exception(f"Подозрительно пустой список подписчиков для аккаунта {account_id} (возможно, ошибка API)")
            # Если подписчиков никогда не было, пустой список - это нормально
            logger.info(f"Аккаунт {account_id} не имеет подписчиков")
            return (0, 0)

        current_ids: set[str] = set()
        current_map: dict[str, dict] = {}
        new_followers_messages: list[str] = []
        unfollow_messages: list[str] = []

        # Обрабатываем новых подписчиков
        for f in followers:
            info = self._extract_info(f)
            fid = info["account_id"]
            if not fid:
                continue

            current_ids.add(fid)
            current_map[fid] = info

            self.followers_meta.setdefault(account_id, {})
            self.followers_meta[account_id][fid] = info

            if fid not in self.known_followers[account_id]:
                msg = self._format_follow_message(info, account_id)
                new_followers_messages.append(msg)

        # Обрабатываем отписавшихся
        unfollowed_ids = self.known_followers[account_id] - current_ids

        for fid in sorted(unfollowed_ids):
            info = self.followers_meta.get(account_id, {}).get(fid, {
                "account_id": fid, "handle": fid, "name": fid
            })
            msg = self._format_unfollow_message(info, account_id)
            unfollow_messages.append(msg)

        # Отправляем сообщения пакетами
        await self._send_batch_messages(new_followers_messages)
        await self._send_batch_messages(unfollow_messages)

        # Сохраняем данные
        self.known_followers[account_id] = current_ids
        self._save_followers_set(account_id)
        self._save_followers_meta(account_id)

        return (len(new_followers_messages), len(unfollow_messages))

    async def check_new_followers(self) -> None:
        async with self._build_session() as session:
            total_new = 0
            total_left = 0
            successful_checks = 0

            for idx, account_id in enumerate(self.account_ids):
                try:
                    logger.info(f"Проверяем аккаунт {account_id} ({idx + 1}/{len(self.account_ids)})")
                    new_count, left_count = await self._check_account_with_retry(session, account_id)
                    total_new += new_count
                    total_left += left_count
                    successful_checks += 1
                    
                    if idx < len(self.account_ids) - 1:
                        await asyncio.sleep(2.0)  # Увеличенная пауза между аккаунтами
                        
                except Exception as e:
                    logger.error(f"Критическая ошибка при проверке аккаунта {account_id}: {e}")
                    error_msg = f"❌ Критическая ошибка при проверке аккаунта {ACCOUNT_ALIASES.get(account_id, account_id)}: {str(e)[:200]}"
                    await self._send_text(error_msg)

            # Отправляем сводку только если есть изменения или если все проверки прошли успешно
            if total_new or total_left or successful_checks == len(self.account_ids):
                parts = []
                if total_new:
                    parts.append(f"🔔 Новых: {total_new}")
                if total_left:
                    parts.append(f"❌ Отписок: {total_left}")
                if successful_checks < len(self.account_ids):
                    parts.append(f"⚠️ Проверено: {successful_checks}/{len(self.account_ids)}")
                
                if parts:
                    summary = f"📊 Сводка: " + ", ".join(parts)
                    await self._send_text(summary)

    async def run_continuous(self, check_interval: int = 300) -> None:
        logger.info(f"Запуск непрерывного мониторинга с интервалом {check_interval} секунд")
        
        consecutive_failures = 0
        max_consecutive_failures = 3
        
        while True:
            try:
                start_time = time.time()
                await self.check_new_followers()
                end_time = time.time()
                
                check_duration = end_time - start_time
                consecutive_failures = 0  # Сбрасываем счетчик ошибок при успехе
                logger.info(f"Проверка завершена за {check_duration:.2f} секунд")
                
                # Адаптивная задержка - если проверка заняла много времени, уменьшаем интервал ожидания
                actual_interval = max(check_interval - check_duration, 60)  # Минимум 60 секунд
                logger.info(f"Следующая проверка через {actual_interval:.0f} секунд")
                
                await asyncio.sleep(actual_interval)
                
            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки")
                break
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"Неожиданная ошибка цикла (попытка {consecutive_failures}): {e}")
                
                # Отправляем уведомление о критической ошибке
                if consecutive_failures == 1:
                    error_msg = f"❌ Критическая ошибка в цикле мониторинга: {str(e)[:200]}"
                    await self._send_text(error_msg)
                elif consecutive_failures >= max_consecutive_failures:
                    error_msg = f"❌ Критическая ошибка: {consecutive_failures} неудачных попыток подряд. Перезапуск через 5 минут."
                    await self._send_text(error_msg)
                    await asyncio.sleep(5 * 60)  # 5 минут при множественных ошибках
                    consecutive_failures = 0  # Сбрасываем счетчик после длительной паузы
                else:
                    # Увеличиваем задержку при повторных ошибках
                    wait_time = min(60 * consecutive_failures, 5 * 60)  # Максимум 5 минут
                    logger.info(f"Ожидание {wait_time} секунд перед повтором")
                    await asyncio.sleep(wait_time)


# ───────────────────────────────────────────────
# main
# ───────────────────────────────────────────────
async def main():
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    CHAT_ID = os.getenv("CHAT_ID")
    ACCOUNT_IDS_STR = os.getenv("SMULE_ACCOUNT_IDS")
    CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    logging.getLogger().setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    if ACCOUNT_IDS_STR:
        ACCOUNT_IDS = [x.strip() for x in ACCOUNT_IDS_STR.split(",") if x.strip()]
    else:
        ACCOUNT_IDS = []

    if not all([TELEGRAM_TOKEN, CHAT_ID, ACCOUNT_IDS]):
        logger.error("❌ ОШИБКА: Не все обязательные переменные настроены!")
        return

    bot = SmuleFollowersBot(TELEGRAM_TOKEN, CHAT_ID, ACCOUNT_IDS)

    startup = [
        "🤖 Бот запущен!",
        f"📊 Отслеживается {len(ACCOUNT_IDS)} аккаунтов:"
    ]
    startup += [f"{i+1}. {ACCOUNT_ALIASES.get(acc, acc)}" for i, acc in enumerate(ACCOUNT_IDS)]
    startup.append(f"⏱ Интервал проверки: {CHECK_INTERVAL} секунд")
    startup.append("🚦 Rate limiting активирован")
    
    await bot._send_text("\n".join(startup))

    await bot.run_continuous(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
