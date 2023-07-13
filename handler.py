import json
import os

from redis import ConnectionPool
from redis import Redis
from telegram import ParseMode
from telegram import Update
from telegram.ext import CallbackContext
from telegram.utils.helpers import escape_markdown

hidden = os.environ["HIDDEN"]

print("os.environ['REDIS_DSN']", os.environ['REDIS_DSN'])

redis_pool = ConnectionPool.from_url(os.environ['REDIS_DSN'])
redis = Redis(connection_pool=redis_pool)


def on_message(update: Update, context: CallbackContext) -> None:
    message = update.message

    if not message:
        return

    text = message.text

    if not text:
        return

    escaped_text = escape_markdown(text, version=2)
    length = len(escaped_text)
    indexes = []
    for char in hidden:
        begin = indexes[-1] if indexes else 0
        index = escaped_text[begin:length].lower().find(char)
        if index != -1:
            indexes.append(index + begin)

    in_sequence = any(indexes[i] + 1 == indexes[i + 1] for i in range(len(indexes) - 1))
    is_equidistant = len(indexes) == len(hidden)
    if is_equidistant and not in_sequence:
        letters = [char for char in escaped_text]
        for i, index in enumerate(indexes):
            letters.insert(index + i, "*")

        indexes = [i for i, char in enumerate(letters) if char == "*"]
        for i, index in enumerate(indexes):
            letters.insert((index + 2) + i, "*")

        user_id = message.from_user.id
        user = message.from_user.name
        one_year_in_seconds = 60 * 60 * 24 * 365

        pipeline = redis.pipeline(transaction=False)
        pipeline.incr(hidden)
        pipeline.incr(f"{hidden}:count:{user_id}")
        pipeline.set(f"{hidden}:user:{user_id}", user)
        pipeline.expire(f"{hidden}:count:{user_id}", one_year_in_seconds)
        pipeline.expire(f"{hidden}:user:{user_id}", one_year_in_seconds)
        count, count_by_author, _, _, _ = pipeline.execute()

        caption = [
            f"Hidden {hidden} detected! {count} have been discovered so far. "
            f"{user} has already worshiped the {hidden} {count_by_author} time(s).",
        ]

        messages = [
            "".join(letters),
            escape_markdown("".join(caption), version=2),
        ]

        message.reply_text("\n\n".join(messages), parse_mode=ParseMode.MARKDOWN_V2)


def leaderboard(update: Update, context: CallbackContext) -> None:
    message = update.message

    if not message:
        return

    get_count = (
        lambda key: int(value.decode()) if (value := redis.get(key)) is not None else 0
    )

    users = {
        key.decode().split(":")[2]: get_count(key)
        for key in redis.scan_iter(f"{hidden}:count:*")
    }

    sorted_users = sorted(users.items(), key=lambda x: x[1], reverse=True)[:10]

    get_username = (
        lambda key: username.decode()
        if (username := redis.get(key)) is not None
        else None
    )

    users = [
        rf"\* [{get_username(f'{hidden}:user:{user[0]}')}](tg://user?id={user[0]}) worshipped the {hidden} {user[1]} times"
        for user in sorted_users  # noqa
    ]

    message.reply_text("\n".join(users), parse_mode=ParseMode.MARKDOWN_V2)


def telegram(event, context):
    body = {
        "message": "Go Serverless v1.0! Your function executed successfully!",
        "input": event,
    }

    response = {"statusCode": 200, "body": json.dumps(body)}

    return response
