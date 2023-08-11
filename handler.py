import json
import os
import re
from functools import wraps
from queue import Queue

from redis import ConnectionPool
from redis import Redis
from redis_rate_limit import RateLimit
from redis_rate_limit import TooManyRequests
from telegram import Bot
from telegram import ParseMode
from telegram import Update
from telegram.ext import CallbackContext
from telegram.ext import CommandHandler
from telegram.ext import Dispatcher
from telegram.ext import Filters
from telegram.ext import MessageHandler
from telegram.utils.helpers import escape_markdown

bot = Bot(token=os.environ["TOKEN"])

redis_pool = ConnectionPool.from_url(os.environ["REDIS_DSN"])
redis = Redis(connection_pool=redis_pool)

word = os.environ["WORD"]


def rate_limit(resource: str = "", expire: int = 60 * 10):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                with RateLimit(
                    redis_pool=redis_pool,
                    resource=resource,
                    client=kwargs["message"].chat.id,
                    max_requests=1,
                    expire=expire,
                ):
                    return func(*args, **kwargs)
            except TooManyRequests:
                pass

        return wrapper

    return decorator


@rate_limit(resource="reply", expire=60 * 60)
def reply(message, text):
    message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


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
    for char in word:
        begin = indexes[-1] if indexes else 0

        fragment = escaped_text[begin:length].lower()

        match = re.search(r"^http\S*", fragment)
        if match:
            begin = match.span()[1]

        index = escaped_text[begin:length].lower().find(char)
        if index != -1:
            indexes.append(index + begin)

    in_sequence = any(indexes[i] + 1 == indexes[i + 1] for i in range(len(indexes) - 1))
    is_equidistant = len(indexes) == len(word)
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
        pipeline.incr(word)
        pipeline.incr(f"{word}:count:{user_id}")
        pipeline.set(f"{word}:user:{user_id}", user)
        pipeline.expire(f"{word}:count:{user_id}", one_year_in_seconds)
        pipeline.expire(f"{word}:user:{user_id}", one_year_in_seconds)
        count, count_by_author, *_ = pipeline.execute()

        caption = [
            f"Hidden {word} detected! {count} have been discovered so far. "
            f"{user} has already worshiped the {word} {count_by_author} time(s).",
        ]

        messages = [
            "".join(letters),
            escape_markdown("".join(caption), version=2),
        ]

        reply(message=message, text="\n\n".join(messages))


def leaderboard(update: Update, context: CallbackContext) -> None:
    message = update.message

    if not message:
        return

    get_count = (
        lambda key: int(value.decode()) if (value := redis.get(key)) is not None else 0
    )

    users = {
        key.decode().split(":")[2]: get_count(key)
        for key in redis.scan_iter(f"{word}:count:*")
    }

    sorted_users = sorted(users.items(), key=lambda x: x[1], reverse=True)[:10]

    get_username = (
        lambda key: username.decode()
        if (username := redis.get(key)) is not None
        else None
    )

    mention = (
        lambda uid: f"[{escape_markdown(get_username(f'{word}:user:{uid}'), version=2)}](tg://user?id={uid})"
    )  # noqa

    users = [
        rf"\* {mention(user[0])} worshipped the {word} {user[1]} times"  # noqa
        for user in sorted_users
    ]

    message.reply_text("\n".join(users), parse_mode=ParseMode.MARKDOWN_V2)


dispatcher = Dispatcher(bot=bot, update_queue=Queue())
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, on_message))
dispatcher.add_handler(CommandHandler("leaderboard", leaderboard))


def telegram(event, context):
    dispatcher.process_update(Update.de_json(json.loads(event["body"]), bot))

    return {
        "statusCode": 200,
    }
