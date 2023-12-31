import abc
import asyncio
import json
import logging
import os
import re
from enum import Enum
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import TypedDict

import aioboto3
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application
from telegram.ext import CommandHandler
from telegram.ext import ContextTypes
from telegram.ext import MessageHandler
from telegram.ext import filters
from telegram.helpers import escape_markdown


class APIGatewayProxyEventV1(TypedDict):
    headers: Dict[str, str]
    body: Optional[str]


class Context(metaclass=abc.ABCMeta):
    pass


application = Application.builder().token(os.environ.get("TELEGRAM_TOKEN", "")).updater(None).build()

boto3 = aioboto3.Session()

logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

word = os.environ["WORD"]

number = int(os.environ["NUMBER"])

pattern = re.compile(r"\d+")


def find_sequence(word: str, message: str) -> List[int]:
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


def find_numbers(message: str) -> Tuple[List[int], int]:
    numbers = pattern.findall(message)

    total = sum(map(int, numbers))

    return numbers, total


async def main(event: APIGatewayProxyEventV1):
    body = event["body"]
    if not body:
        return

    async with application:
        await application.process_update(Update.de_json(json.loads(body), application.bot))


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
        event["headers"].get("X-Telegram-Bot-Api-Secret-Token"),
        os.environ["SECRET"],
    ):
        return {
            "statusCode": 401,
        }

    asyncio.get_event_loop().run_until_complete(main(event))

    return {
        "statusCode": 200,
    }


class Kind(Enum):
    WORD = "word"
    NUMBER = "number"


async def store_and_compute(key: dict[str, str], name: str, kind: Kind):
    async with boto3.resource("dynamodb") as dynamodb:
        table = await dynamodb.Table(os.environ[f"USER_{kind.value.upper()}_TABLE"])
        global_table = await dynamodb.Table(os.environ[f"GLOBAL_{kind.value.upper()}_TABLE"])

        [response, global_response] = await asyncio.gather(
            table.update_item(
                Key=key,
                UpdateExpression="SET score = if_not_exists(score, :start) + :inc, #n = :name",
                ExpressionAttributeNames={"#n": "name"},
                ExpressionAttributeValues={
                    ":start": 0,
                    ":inc": 1,
                    ":name": name,
                },
                ReturnValues="UPDATED_NEW",
            ),
            global_table.update_item(
                Key={"id": "global"},
                UpdateExpression="SET score = if_not_exists(score, :start) + :inc",
                ExpressionAttributeValues={":start": 0, ":inc": 1},
                ReturnValues="UPDATED_NEW",
            ),
        )

        score = response["Attributes"]["score"]
        global_score = global_response["Attributes"]["score"]
        return score, global_score


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message:
        return

    user = message.from_user
    if not user:
        return

    text = message.text
    if not text:
        return

    text = escape_markdown(text.lower(), version=2)

    indexes = find_sequence(word, text)

    mention = f"[{user.username}](tg://user?id={user.id})"

    key = {"id": str(user.id)}

    name = user.username or user.first_name

    is_same_length = len(indexes) == len(word)

    if is_same_length:
        letters = [char for char in text]
        for i, index in enumerate(indexes):
            letters.insert(index + i, "*")

        indexes = [i for i, char in enumerate(letters) if char == "*"]
        for i, index in enumerate(indexes):
            letters.insert((index + 2) + i, "*")

        score, global_score = await store_and_compute(key, name, Kind.WORD)

        caption = [
            f"Hidden {word.upper()} detected\!\n",
            f"{mention} has already worshiped the {word} {score} times\.\n",
            f"{global_score} have been discovered so far\.\n",
        ]

        messages = [
            "".join(letters),
            "".join(caption),
        ]

        await message.reply_text("\n\n".join(messages), parse_mode=ParseMode.MARKDOWN_V2)

    numbers, total = find_numbers(text)
    if total == number:
        score, global_score = await store_and_compute(key, name, Kind.NUMBER)
        formula = " \+ ".join(str(i) for i in numbers)
        messages = [
            f"{formula} \= {total}",
            f"{mention} has already made {number} {score} times\!",
        ]

        await message.reply_text("\n\n".join(messages), parse_mode=ParseMode.MARKDOWN_V2)


async def on_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message:
        return

    async with boto3.resource("dynamodb") as dynamodb:
        table = await dynamodb.Table(os.environ["USER_WORD_TABLE"])

        scan_kwargs = {
            "ExpressionAttributeNames": {"#n": "name"},
            "ProjectionExpression": "id, #n, score",
        }

        items = []

        while True:
            response = await table.scan(**scan_kwargs)
            items.extend(response["Items"])
            if "LastEvaluatedKey" not in response:
                break
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

        top_users = [
            rf"\* [{item['name']}](tg://user?id={item['id']}) has worshipped the {word.upper()} {int(item['score'])} times"
            for item in sorted(items, key=lambda i: int(i["score"]), reverse=True)[:10]
        ]

        await message.reply_text("\n".join(top_users), parse_mode=ParseMode.MARKDOWN_V2)


application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
application.add_handler(CommandHandler("leaderboard", on_leaderboard))
