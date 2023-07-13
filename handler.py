import json
import os

from redis import ConnectionPool
from redis import Redis
from telegram import ParseMode
from telegram import Update
from telegram.ext import CallbackContext
from telegram.utils.helpers import escape_markdown

p = os.environ["p"]

redis_pool = ConnectionPool.from_url(os.environ["REDIS_DSN"])
redis = Redis(connection_pool=redis_pool)


def meme(update: Update, context: CallbackContext) -> None:
    message = update.message

    if not message:
        return

    text = message.text

    if not text:
        return

    escaped_text = escape_markdown(text, version=2)
    length = len(escaped_text)
    indexes = []
    for char in p:
        begin = indexes[-1] if indexes else 0
        index = escaped_text[begin:length].lower().find(char)
        if index != -1:
            indexes.append(index + begin)

    in_sequence = any(indexes[i] + 1 == indexes[i + 1] for i in range(len(indexes) - 1))
    is_equidistant = len(indexes) == len(p)
    if is_equidistant and not in_sequence:
        letters = [char for char in escaped_text]
        for i, index in enumerate(indexes):
            letters.insert(index + i, "*")

        indexes = [i for i, char in enumerate(letters) if char == "*"]
        for i, index in enumerate(indexes):
            letters.insert((index + 2) + i, "*")

        user_id = message.from_user.id
        user = message.from_user.name

        pipeline = redis.pipeline(transaction=False)
        pipeline.incr(p)
        pipeline.incr(f"{p}:count:{user_id}")
        pipeline.set(f"{p}:user:{user_id}", user)
        count, count_by_author, _ = pipeline.execute()

        caption = [
            f"Hidden {p} detected! {count} have been discovered so far. "
            f"{user} has already worshiped the {p} {count_by_author} time(s).",
        ]

        messages = [
            "".join(letters),
            escape_markdown("".join(caption), version=2),
        ]

        message.reply_text("\n\n".join(messages), parse_mode=ParseMode.MARKDOWN_V2)


def hello(event, context):
    body = {
        "message": "Go Serverless v1.0! Your function executed successfully!",
        "input": event,
    }

    response = {"statusCode": 200, "body": json.dumps(body)}

    return response
