import abc
import asyncio
import json
import logging
import os
from typing import Dict
from typing import Optional
from typing import TypedDict

import aioboto3
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application
from telegram.ext import ContextTypes
from telegram.ext import MessageHandler
from telegram.ext import filters
from telegram.helpers import escape_markdown


class APIGatewayProxyEventV1(TypedDict):
    headers: Dict[str, str]
    body: Optional[str]


class Context(metaclass=abc.ABCMeta):
    pass


application = (
    Application.builder()
    .token(os.environ.get("TELEGRAM_TOKEN", ""))
    .updater(None)
    .build()
)

boto3 = aioboto3.Session()

logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

word = os.environ["WORD"]


def find_seq(word, message):
    indices = []
    word_index = 0
    current_index = 0

    words = message.split()

    for w in words:
        if word_index < len(word):
            if w[0] == word[word_index]:
                indices.append(current_index)
                word_index += 1
            else:
                indices = []
                word_index = 0
                if w[0] == word[word_index]:
                    indices.append(current_index)
                    word_index += 1
        current_index += len(w) + 1

    return indices if word_index == len(word) else []


async def main(event: APIGatewayProxyEventV1):
    body = event["body"]
    if not body:
        return

    async with application:
        await application.process_update(
            Update.de_json(json.loads(body), application.bot)
        )


def equals(left, right):
    if not left or not right:
        return False

    if len(left) != len(right):
        return False

    for c1, c2 in zip(left, right):
        if c1 != c2:
            return False

    return True


def telegram(event: APIGatewayProxyEventV1, context: Context):
    if not equals(
        event["headers"].get("x-telegram-bot-api-secret-token"),
        os.environ["SECRET"],
    ):
        print(
            ">>> invalid secret",
            event["headers"].get("x-telegram-bot-api-secret-token"),
            os.environ["SECRET"],
        )
        return {
            "statusCode": 401,
        }

    asyncio.get_event_loop().run_until_complete(main(event))

    print(">>> success")
    return {
        "statusCode": 200,
    }


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message:
        print(">>> no message")
        return

    user = message.from_user
    if not user:
        print(">>> no user")
        return

    text = message.text
    if not text:
        print(">>> no text")
        return

    # escaped_text = escape_markdown(text, version=2)
    text = escape_markdown(text, version=2)

    indexes = find_seq(word, text)

    print(">>> text", text)
    print(">>> indexes", indexes)
    print(">>> word", word)

    is_same_length = len(indexes) == len(word)

    if is_same_length:
        letters = [char for char in text]
        for i, index in enumerate(indexes):
            letters.insert(index + i, "*")

        indexes = [i for i, char in enumerate(letters) if char == "*"]
        for i, index in enumerate(indexes):
            letters.insert((index + 2) + i, "*")

        count = 1
        count_by_author = 3
        # user_id = message.from_user.id
        user = message.from_user.name

        caption = [
            f"Hidden {word} detected! {count} have been discovered so far. "
            f"{user} has already worshiped the {word} {count_by_author} time(s).",
        ]

        messages = [
            "".join(letters),
            escape_markdown("".join(caption), version=2),
        ]

        await message.reply_text(
            "\n\n".join(messages), parse_mode=ParseMode.MARKDOWN_V2
        )


application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
# application.add_handler(CommandHandler("leaderboard", leaderboard))
