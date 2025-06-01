import os
import re
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import Application, ContextTypes
from notion_client import Client, APIResponseError
from dateutil import parser as date_parser

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_ROOT_PAGE_URL = os.getenv("NOTION_ROOT_PAGE_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/Madrid")
SKIP_TITLE_PREFIXES = ["[DRAFT]", "[TG_SYNC]"]

def extract_notion_page_id(url: str) -> str:
    match = re.search(
        r'([0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
        url, re.I
    )
    return match.group(1).replace('-', '') if match else ''

def escape_markdown_v2(text: str) -> str:
    chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([%s])' % re.escape(chars), r'\\\1', text)

def escape_telegram_nicknames(text: str) -> str:
    return re.sub(r'@([a-zA-Z0-9_]+)', lambda m: '@' + m.group(1).replace('_', '\\_'), text)

class NotionHandler:
    SYNC_DB_TITLE = SKIP_TITLE_PREFIXES[1] + " Timestamp"

    def __init__(self):
        self.client = Client(auth=NOTION_API_KEY)
        self.root_id = extract_notion_page_id(NOTION_ROOT_PAGE_URL)
        self.sync_db_id = self.get_or_create_sync_database()

    def get_first_level_pages(self):
        try:
            all_children = []
            cursor = None
            while True:
                logging.info(f"Fetching Notion children for root_id={self.root_id}, cursor={cursor}")
                response = self.client.blocks.children.list(self.root_id, start_cursor=cursor)
                all_children.extend(response.get("results", []))
                cursor = response.get("next_cursor")
                if not cursor:
                    break
            logging.info(f"Fetched {len(all_children)} children from Notion root page")
            return [
                self.client.pages.retrieve(page_id=b["id"])
                for b in all_children
                if b.get("type") == "child_page"
            ]
        except APIResponseError as e:
            logging.error(f"Notion API error in get_first_level_pages: {e}")
            return []
        except Exception as e:
            logging.error(f"Unexpected error in get_first_level_pages: {e}")
            return []

    def get_page_content(self, page_id):
        try:
            # Add page title to log
            page = self.client.pages.retrieve(page_id)
            title = page.get("properties", {}).get("title", {}).get("title", [{}])[0].get("plain_text", "")
            logging.info(f"Fetching Notion page content for page_id={page_id}, title={title}")
            blocks = self.client.blocks.children.list(page_id).get("results", [])
            lines = []
            for b in blocks:
                parsed = self.parse_block(b)
                if parsed:
                    lines.append(parsed)
            logging.info(f"Fetched {len(blocks)} blocks for page_id={page_id}")
            return "".join(lines).strip()
        except APIResponseError as e:
            logging.error(f"Content error in get_page_content for page_id={page_id}: {e}")
            return ""
        except Exception as e:
            logging.error(f"Unexpected error in get_page_content for page_id={page_id}: {e}")
            return ""

    def parse_block(self, block):
        try:
            t = block["type"]
            if t == "paragraph":
                return self._parse_rich_text(block["paragraph"]["rich_text"]) + "\n\n"
            if t in ("heading_1", "heading_2", "heading_3"):
                text = self._parse_rich_text(block[t]["rich_text"])
                return f"*{text}*\n\n"
            if t == "bulleted_list_item":
                return f"\\- {self._parse_rich_text(block[t]['rich_text'])}\n"
            if t == "numbered_list_item":
                return f"1\\. {self._parse_rich_text(block[t]['rich_text'])}\n"
            if t == "toggle":
                summary = self._parse_rich_text(block["toggle"]["rich_text"])
                children = self.client.blocks.children.list(block["id"]).get("results", [])
                content = "".join([self.parse_block(child) for child in children]).strip()
                if content:
                    return f"*{summary}*\n||{content}||\n\n"
                else:
                    return f"||{summary}||\n\n"
            if t == "quote":
                text = self._parse_rich_text(block["quote"]["rich_text"])
                return f"> {text}\n\n"
            if t == "callout":
                emoji = block["callout"]["icon"].get("emoji", "")
                text = self._parse_rich_text(block["callout"]["rich_text"])
                return f"{emoji} {text}\n\n"
            if t == "code":
                text = self._parse_rich_text(block["code"]["rich_text"])
                lang = block["code"]["language"]
                return f"``````\n\n"
            if t == "divider":
                return "------\n\n"
            if t == "image":
                image_type = block["image"]["type"]
                url = block["image"][image_type]["url"]
                return f"![]({url})\n\n"
            if t == "table":
                return self._parse_table(block)
            if t == "table_row":
                return self._parse_table_row(block)
            # Log unsupported block types
            logging.warning(f"Unsupported Notion block type: {t} (block id: {block.get('id')})")
            return ""
        except Exception as e:
            logging.error(f"Error parsing block: {e} | Block: {block}")
            return ""

    def _parse_table(self, block):
        rows = self.client.blocks.children.list(block["id"])["results"]
        lines = [self._parse_table_row(row) for row in rows]
        table_text = "\n".join(lines)
        return f"``````\n\n"

    def _parse_table_row(self, row_block):
        cells = row_block["table_row"]["cells"]
        return " | ".join(self._parse_rich_text(cell, escape=False) for cell in cells)

    def _parse_rich_text(self, rich_text, escape=True):
        result = []
        for segment in rich_text:
            text = segment.get("plain_text", "")
            href = segment.get("href")
            annotations = segment.get("annotations", {})

            if annotations.get("bold"):
                text = f"*{escape_markdown_v2(text) if escape else text}*"
            elif annotations.get("italic"):
                text = f"_{escape_markdown_v2(text) if escape else text}_"
            elif annotations.get("strikethrough"):
                text = f"~{escape_markdown_v2(text) if escape else text}~"
            elif annotations.get("code"):
                text = f"`{escape_markdown_v2(text) if escape else text}`"
            elif annotations.get("underline"):
                text = f"__{escape_markdown_v2(text) if escape else text}__"
            else:
                text = escape_markdown_v2(text) if escape else text

            text = escape_telegram_nicknames(text) if escape else text

            if href:
                text = f"[{text}]({href})"

            result.append(text)
        return "".join(result)

    def get_or_create_sync_database(self):
        children = self.client.blocks.children.list(self.root_id)["results"]
        for b in children:
            if b.get("type") == "child_database":
                db = self.client.databases.retrieve(b["id"])
                title = db["title"][0]["plain_text"] if db["title"] else ""
                if title == self.SYNC_DB_TITLE:
                    # Ensure PageTitle property exists
                    props = db.get("properties", {})
                    if "PageTitle" not in props:
                        self.client.databases.update(
                            db["id"],
                            properties={
                                "PageTitle": {"rich_text": {}}
                            }
                        )
                    return b["id"]
        db = self.client.databases.create(
            parent={"type": "page_id", "page_id": self.root_id},
            title=[{"type": "text", "text": {"content": self.SYNC_DB_TITLE}}],
            properties={
                "Страница": {"title": {}},
                "Telegram": {"url": {}},
                "Обновлено": {"date": {}},
                "PageTitle": {"rich_text": {}}
            }
        )
        logging.info(f"Создана служебная база данных: {db['id']}")
        return db["id"]

    def update_sync_database(self, sync_data):
        if not sync_data:
            logging.info("Нет обновлений для служебной базы, обновление не требуется.")
            return

        db_id = self.get_or_create_sync_database()
        existing_rows = {}
        query = self.client.databases.query(db_id)
        for row in query["results"]:
            # Use Notion page_id (from URL) as unique key, but also store title for tracking
            notion_url = ""
            title = ""
            if row["properties"].get("Страница", {}).get("title"):
                title = row["properties"]["Страница"]["title"][0]["plain_text"]
                link = row["properties"]["Страница"]["title"][0].get("href")
                if link:
                    notion_url = link
            page_id = ""
            if notion_url:
                m = re.search(r'([0-9a-f]{32})', notion_url)
                if m:
                    page_id = m.group(1)
            if page_id:
                existing_rows[page_id] = {
                    "row_id": row["id"],
                    "title": title
                }

        page_ids_in_data = set()
        for title, notion_url, tg_url, dt in sync_data:
            # Extract Notion page_id from URL
            m = re.search(r'([0-9a-f]{32})', notion_url)
            page_id = m.group(1) if m else ""
            page_ids_in_data.add(page_id)
            props = {
                "Страница": {
                    "title": [
                        {"type": "text", "text": {"content": title, "link": {"url": notion_url}}}
                    ]
                },
                "Telegram": {"url": tg_url if tg_url else None},
                "Обновлено": {"date": {"start": dt}},
                "PageTitle": {"rich_text": [{"type": "text", "text": {"content": title}}]}
            }
            if page_id in existing_rows:
                self.client.pages.update(existing_rows[page_id]["row_id"], properties=props)
            else:
                self.client.pages.create(parent={"database_id": db_id}, properties=props)

        for page_id, row_info in existing_rows.items():
            if page_id not in page_ids_in_data:
                self.client.pages.update(row_info["row_id"], archived=True)

    def get_sync_db_mapping(self):
        """Return a mapping: page_id -> {'message_id': ..., 'last_edited': ..., 'title': ...} from the sync DB."""
        db_id = self.get_or_create_sync_database()
        mapping = {}
        query = self.client.databases.query(db_id)
        for row in query["results"]:
            props = row["properties"]
            notion_url = ""
            title = ""
            if props.get("Страница", {}).get("title"):
                title = props["Страница"]["title"][0].get("plain_text", "")
                link = props["Страница"]["title"][0].get("href")
                if link:
                    notion_url = link
            tg_url = props.get("Telegram", {}).get("url", "")
            last_edited = props.get("Обновлено", {}).get("date", {}).get("start", "")
            # Extract Notion page_id from URL
            page_id = ""
            if notion_url:
                m = re.search(r'([0-9a-f]{32})', notion_url)
                if m:
                    page_id = m.group(1)
            if page_id:
                message_id = ""
                if tg_url:
                    m = re.search(r'/(\d+)$', tg_url)
                    message_id = m.group(1) if m else ""
                mapping[page_id] = {
                    "message_id": int(message_id) if message_id else "",
                    "last_edited": last_edited,
                    "title": title
                }
        return mapping

class TelegramBot:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.notion = NotionHandler()
        self.pinned = self.notion.get_sync_db_mapping()
        print(self.pinned)

    def _normalize_page_id(self, page_id):
        return page_id.replace("-", "")

    def _to_timestamp(self, dt):
        if not dt:
            return 0
        if isinstance(dt, (int, float)):
            return int(dt)
        try:
            return int(date_parser.parse(dt).timestamp())
        except Exception:
            return 0

    async def sync(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            pages = self.notion.get_first_level_pages()
            current_page_ids = set()
            sync_data = []
            for page in pages:
                try:
                    page_id = self._normalize_page_id(page["id"])
                    current_page_ids.add(page_id)
                    title = page.get("properties", {}).get("title", {}).get("title", [{}])[0].get("plain_text", "")
                    if title.strip().startswith(tuple(SKIP_TITLE_PREFIXES)):
                        logging.info(f"Skipping page '{title}' due to prefix.")
                        continue
                    last_edited = page.get("last_edited_time")
                    tg_post_id = self.pinned.get(page_id, {}).get("message_id", "")
                    tg_url = f"https://t.me/c/{TELEGRAM_CHAT_ID.replace('-100', '')}/{tg_post_id}" if tg_post_id else ""

                    prev_last_edited = self.pinned.get(page_id, {}).get("last_edited")
                    last_edited_ts = self._to_timestamp(last_edited)
                    prev_last_edited_ts = self._to_timestamp(prev_last_edited)
                    need_update = last_edited_ts != prev_last_edited_ts

                    logging.info(
                        f"Decision for page '{title}' (id={page_id}): "
                        f"last_edited in Notion={last_edited} (ts={last_edited_ts}), "
                        f"last_edited in pinned={prev_last_edited} (ts={prev_last_edited_ts}), "
                        f"need_update={need_update}"
                    )

                    if need_update:
                        logging.info(f"Syncing page '{title}' (id={page_id}) to Telegram (will edit and re-pin post).")
                        content = self.notion.get_page_content(page["id"])
                        message = f"*{escape_markdown_v2(title)}*\n\n{content}" if content else f"*{escape_markdown_v2(title)}*"
                        if tg_post_id:
                            try:
                                await self.bot.edit_message_text(
                                    chat_id=TELEGRAM_CHAT_ID,
                                    message_id=int(tg_post_id),
                                    text=message,
                                    parse_mode="MarkdownV2",
                                    disable_web_page_preview=True
                                )
                                await self.bot.pin_chat_message(
                                    chat_id=TELEGRAM_CHAT_ID,
                                    message_id=int(tg_post_id),
                                    disable_notification=False
                                )
                                # Fix: update both message_id and last_edited in pinned
                                self.pinned[page_id] = {"message_id": int(tg_post_id), "last_edited": last_edited}
                            except Exception as e:
                                logging.warning(f"Failed to edit or pin Telegram message {tg_post_id} for page {title}: {e}")
                                await self.create_post(page_id, message, last_edited)
                                tg_post_id = self.pinned.get(page_id, {}).get("message_id", "")
                        else:
                            await self.create_post(page_id, message, last_edited)
                            tg_post_id = self.pinned.get(page_id, {}).get("message_id", "")
                        tg_url = f"https://t.me/c/{TELEGRAM_CHAT_ID.replace('-100', '')}/{tg_post_id}" if tg_post_id else ""
                        sync_data.append((title, f"https://www.notion.so/{page_id}", tg_url, last_edited))
                    else:
                        logging.info(f"No sync needed for page '{title}' (id={page_id}).")
                        sync_data.append((title, f"https://www.notion.so/{page_id}", tg_url, last_edited))
                except Exception as e:
                    logging.error(f"Error processing page {page.get('id', 'unknown')}: {e}")

            self.cleanup_posts(current_page_ids)

            if sync_data:
                self.notion.update_sync_database(sync_data)
                self.pinned = self.notion.get_sync_db_mapping()

        except Exception as e:
            logging.error(f"Critical sync error: {e}")

    async def create_post(self, page_id, text, last_edited):
        try:
            msg = await self.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=text,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True
            )
            await self.bot.pin_chat_message(
                chat_id=TELEGRAM_CHAT_ID,
                message_id=msg.message_id,
                disable_notification=False
            )
            # Fix: update both message_id and last_edited in pinned
            self.pinned[page_id] = {"message_id": msg.message_id, "last_edited": last_edited}
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Failed to create post: {error_msg}")
            self._log_message_context(page_id, text, error_msg)

    def cleanup_posts(self, current_ids):
        for page_id in list(self.pinned.keys()):
            if page_id not in current_ids:
                try:
                    message_id = self.pinned[page_id]["message_id"]
                    try:
                        self.bot.unpin_chat_message(
                            chat_id=TELEGRAM_CHAT_ID,
                            message_id=message_id
                        )
                    except Exception as e:
                        logging.warning(f"Failed to unpin message {message_id}: {e}")
                    try:
                        self.bot.delete_message(
                            chat_id=TELEGRAM_CHAT_ID,
                            message_id=message_id
                        )
                    except Exception as e:
                        logging.warning(f"Failed to delete message {message_id}: {e}")
                    del self.pinned[page_id]
                except Exception as e:
                    logging.error(f"Cleanup error for {page_id}: {e}")

    def _log_message_context(self, page_id, text, error_msg):
        if "Can't parse entities" in error_msg or "parse" in error_msg:
            match = re.search(r'at byte offset (\d+)', error_msg)
            if match:
                error_pos = int(match.group(1))
                context = self._get_error_context(text, error_pos)
                logging.error(f"Markdown error context for page {page_id}:\n{context}")
            else:
                logging.error(f"Problematic content for page {page_id}:\n{text[:2000]}...")
        with open(f"error_{page_id}.txt", "w", encoding="utf-8") as f:
            f.write(text)

    def _get_error_context(self, text, error_pos):
        try:
            encoded = text.encode("utf-8")
            start = max(0, error_pos - 50)
            end = min(len(encoded), error_pos + 50)
            snippet_bytes = encoded[start:end]
            snippet = snippet_bytes.decode("utf-8", errors="replace")
            marker = ' ' * (error_pos - start) + '▼'
            return (
                f"Error position: {error_pos} (total bytes: {len(encoded)})\n"
                f"Context:\n{snippet}\n{marker}"
            )
        except Exception as e:
            logging.error(f"Ошибка формирования контекста: {e}")
            return "Не удалось получить контекст"

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    bot = TelegramBot()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.job_queue.run_repeating(bot.sync, interval=SYNC_INTERVAL)
    app.run_polling()
