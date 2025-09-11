import asyncio
import aiohttp
import json
import os
import ssl
import certifi
from telegram import Bot
from telegram.error import TelegramError
import logging
from datetime import datetime
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────────────
# env + логирование
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SmuleFollowersBot:
    def __init__(self, telegram_token: str, chat_id: str, account_ids):
        """
        Args:
            telegram_token: токен Telegram-бота
            chat_id: чат для уведомлений
            account_ids: list[str] аккаунтов Smule
        """
        self.bot = Bot(token=telegram_token)
        self.chat_id = chat_id
        self.account_ids = account_ids if isinstance(account_ids, list) else [account_ids]

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
        self.followers_meta: dict[str, dict[str, dict]] = {}  # {account_id: {follower_id: info}}

        for account_id in self.account_ids:
            self.known_followers[account_id] = self._load_followers_set(account_id)
            self.followers_meta[account_id] = self._load_followers_meta(account_id)

    # ──────────────────────────────────────────────────────────────────────────
    # Работа с файлами (слепок id и метаданные)
    # ──────────────────────────────────────────────────────────────────────────
    def _followers_file(self, account_id: str) -> str:
        return f"followers_{account_id}.json"

    def _followers_meta_file(self, account_id: str) -> str:
        return f"followers_meta_{account_id}.json"

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

    # ──────────────────────────────────────────────────────────────────────────
    # HTTP-сессия с валидным CA (certifi)
    # ──────────────────────────────────────────────────────────────────────────
    def _build_session(self) -> aiohttp.ClientSession:
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        timeout = aiohttp.ClientTimeout(total=30, connect=15, sock_read=15)
        connector = aiohttp.TCPConnector(ssl=ssl_ctx, limit=10)
        return aiohttp.ClientSession(connector=connector, timeout=timeout)

    # ──────────────────────────────────────────────────────────────────────────
    # Smule API + ретраи
    # ──────────────────────────────────────────────────────────────────────────
    async def _get_followers_page(self, session: aiohttp.ClientSession,
                                  account_id: str, offset: int = 0, limit: int = 20) -> dict | None:
        url = "https://www.smule.com/api/profile/followers"
        params = {"accountId": account_id, "offset": offset, "limit": limit}

        for attempt in range(1, 4):
            try:
                async with session.get(url, params=params, headers=self.headers) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    text = await resp.text()
                    logger.error(f"HTTP {resp.status} {url} {params} → {text[:300]}")
                    return None
            except aiohttp.ClientSSLError as e:
                logger.error(f"TLS ошибка (Smule, {account_id}): {e}")
                return None
            except Exception as e:
                logger.warning(f"Попытка {attempt}/3, ошибка сети ({account_id}): {e}")
                await asyncio.sleep(1.5 * attempt)
        return None

    async def _get_all_followers(self, session: aiohttp.ClientSession, account_id: str) -> list[dict]:
        all_followers: list[dict] = []
        offset, limit = 0, 20

        while True:
            data = await self._get_followers_page(session, account_id, offset, limit)
            if not data or "list" not in data:
                break

            batch = data["list"] or []
            all_followers.extend(batch)
            if len(batch) < limit:
                break

            offset += limit
            await asyncio.sleep(0.5)  # мягкий rate-limit

        return all_followers

    # ──────────────────────────────────────────────────────────────────────────
    # Обработка и уведомления
    # ──────────────────────────────────────────────────────────────────────────
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
        lines = [
            "🎵 Новый подписчик!",
            "",
            f"📊 Аккаунт Smule: {account_id}",
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
        lines = [
            "❌ Подписчик отписался!",
            "",
            f"📊 Аккаунт Smule: {account_id}",
            f"👤 Имя: {info.get('name', 'Unknown')}",
            f"📝 Ник: @{info.get('handle', 'Unknown')}",
            f"🔗 Профиль: https://www.smule.com/{info.get('handle', 'Unknown')}",
            f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        return "\n".join(lines)

    async def _send_text(self, text: str) -> None:
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=text)
            logger.info("Уведомление отправлено в Telegram")
        except TelegramError as e:
            logger.error(f"Ошибка отправки в Telegram: {e}")

    async def _check_account(self, session: aiohttp.ClientSession, account_id: str) -> tuple[int, int]:
        """
        Возвращает (new_count, unfollow_count)
        """
        logger.info(f"Проверяем подписчиков для аккаунта {account_id}…")
        followers = await self._get_all_followers(session, account_id)
        if not followers:
            logger.warning(f"Не удалось получить список подписчиков для аккаунта {account_id}")
            return (0, 0)

        logger.info(f"Получено {len(followers)} подписчиков для аккаунта {account_id}")

        new_count = 0
        current_ids: set[str] = set()

        # карта id → info по текущей выборке
        current_map: dict[str, dict] = {}

        for f in followers:
            info = self._extract_info(f)
            fid = info["account_id"]
            if not fid:
                continue

            current_ids.add(fid)
            current_map[fid] = info

            # пополним диск метаданных (для будущих отписок)
            self.followers_meta.setdefault(account_id, {})
            self.followers_meta[account_id][fid] = info

            # Новый подписчик
            if fid not in self.known_followers[account_id]:
                msg = self._format_follow_message(info, account_id)
                await self._send_text(msg)
                new_count += 1
                await asyncio.sleep(0.3)

        # Отписавшиеся (были в слепке, но их нет сейчас)
        unfollowed_ids = self.known_followers[account_id] - current_ids
        unfollow_count = len(unfollowed_ids)

        for fid in sorted(unfollowed_ids):
            # достанем сохранённую мету (если есть), чтобы показать handle/name
            info = self.followers_meta.get(account_id, {}).get(fid, {
                "account_id": fid, "handle": fid, "name": fid
            })
            msg = self._format_unfollow_message(info, account_id)
            await self._send_text(msg)
            await asyncio.sleep(0.3)

            # можно по желанию удалять метаданные отписавшихся, но я оставляю
            # чтобы сохранить историю ников; если хочешь чистить — раскомментируй:
            # self.followers_meta[account_id].pop(fid, None)

        # Обновим слепок и мету на диск
        self.known_followers[account_id] = current_ids
        self._save_followers_set(account_id)
        self._save_followers_meta(account_id)

        if new_count:
            logger.info(f"Найдено {new_count} новых подписчиков для {account_id}")
        else:
            logger.info(f"Новых подписчиков нет для {account_id}")
        if unfollow_count:
            logger.info(f"{unfollow_count} подписчик(ов) отписались от {account_id}")

        return (new_count, unfollow_count)

    async def check_new_followers(self) -> None:
        async with self._build_session() as session:
            total_new = 0
            total_left = 0

            for idx, account_id in enumerate(self.account_ids):
                try:
                    new_count, left_count = await self._check_account(session, account_id)
                    total_new += new_count
                    total_left += left_count
                    if idx < len(self.account_ids) - 1:
                        await asyncio.sleep(1.0)
                except Exception as e:
                    logger.error(f"Ошибка при проверке аккаунта {account_id}: {e}")
                    await self._send_text(f"❌ Ошибка при проверке аккаунта {account_id}: {e}")

            # Итоговая сводка (если было хоть что-то)
            if total_new or total_left:
                parts = []
                if total_new:
                    parts.append(f"🔔 Новых: {total_new}")
                if total_left:
                    parts.append(f"❌ Отписок: {total_left}")
                await self._send_text(f"📊 Сводка: " + ", ".join(parts))

    async def run_continuous(self, check_interval: int = 300) -> None:
        logger.info(f"Запускаем непрерывную проверку для {len(self.account_ids)} аккаунтов с интервалом {check_interval} секунд")
        logger.info(f"Отслеживаемые аккаунты: {', '.join(self.account_ids)}")

        while True:
            try:
                await self.check_new_followers()
                logger.info(f"Ожидаем {check_interval} секунд до следующей проверки…")
                await asyncio.sleep(check_interval)
            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки")
                break
            except Exception as e:
                logger.error(f"Неожиданная ошибка цикла: {e}")
                await asyncio.sleep(60)


# ──────────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────────
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
        logger.error("")
        logger.error("📝 Пример .env:")
        logger.error("=" * 50)
        logger.error("TELEGRAM_TOKEN=ваш_токен_бота")
        logger.error("CHAT_ID=ваш_chat_id")
        logger.error("SMULE_ACCOUNT_IDS=96242367,3150102762")
        logger.error("CHECK_INTERVAL=1800   # каждые 30 минут")
        logger.error("LOG_LEVEL=INFO")
        logger.error("=" * 50)
        return

    logger.info(f"Настройки загружены. Будут отслеживаться {len(ACCOUNT_IDS)} аккаунтов: {', '.join(ACCOUNT_IDS)}")

    bot = SmuleFollowersBot(TELEGRAM_TOKEN, CHAT_ID, ACCOUNT_IDS)

    # Сообщение о запуске
    startup = [
        "🤖 Бот запущен!",
        f"📊 Отслеживается {len(ACCOUNT_IDS)} аккаунтов:"
    ]
    startup += [f"{i+1}. {acc}" for i, acc in enumerate(ACCOUNT_IDS)]
    startup.append(f"⏱ Интервал проверки: {CHECK_INTERVAL} секунд")
    await bot._send_text("\n".join(startup))

    await bot.run_continuous(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
