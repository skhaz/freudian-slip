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

    indexes = find_seq(word, text)

    is_same_length = len(indexes) == len(word)

    if is_same_length:
        letters = [char for char in text]
        for i, index in enumerate(indexes):
            letters.insert(index + i, "*")

        indexes = [i for i, char in enumerate(letters) if char == "*"]
        for i, index in enumerate(indexes):
            letters.insert((index + 2) + i, "*")

        key = {"id": str(user.id)}

        async with boto3.resource("dynamodb") as dynamodb:
            table = await dynamodb.Table(os.environ["USER_TABLE"])
            global_table = await dynamodb.Table(os.environ["GLOBAL_TABLE"])

            [response, global_response] = await asyncio.gather(
                table.update_item(
                    Key=key,
                    UpdateExpression="SET score = if_not_exists(score, :start) + :inc",
                    ExpressionAttributeValues={":start": 0, ":inc": 1},
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

            mention = f"[{user.username}](tg://user?id={user.id})"

            caption = [
                f"Hidden {word.upper()} detected\!\n"
                f"{mention} has already worshiped the {word} {score} times\.\n",
                f"{global_score} have been discovered so far\.\n",
            ]

            messages = [
                "".join(letters),
                "".join(caption),
            ]

            await message.reply_text(
                "\n\n".join(messages), parse_mode=ParseMode.MARKDOWN_V2
            )


# async def scan(table, **kwargs):
#     response = table.scan(**kwargs)
#     from response["Items"]
#     while response.get("LastEvaluatedKey"):
#         response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"], **kwargs)
#         yield from response["Items"]

import decimal


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return str(o)
        return super().default(o)


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message:
        return

    async with boto3.resource("dynamodb") as dynamodb:
        result = []
        table = await dynamodb.Table(os.environ["USER_TABLE"])
        scan_kwargs = {"ProjectionExpression": "score"}
        while True:
            response = await table.scan(**scan_kwargs)
            result.extend(response["Items"])
            if "LastEvaluatedKey" not in response:
                break
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

        message.reply_text(json.dumps(result, cls=DecimalEncoder))
        # items = []
        # scan_kwargs = {"TableName": os.environ["USER_TABLE"]}
        # done = False
        # start_key = None

        # while not done:
        #     if start_key:
        #         scan_kwargs["ExclusiveStartKey"] = start_key
        #     response = await dynamodb.scan(**scan_kwargs)
        #     items.extend(response.get("Items", []))
        #     start_key = response.get("LastEvaluatedKey", None)
        #     done = start_key is None

        # sorted_items = sorted(items, key=lambda i: int(i["score"]["N"]), reverse=True)[:10]  # fmt: skip

        # top_users = [
        #     {"user": item["user"]["S"], "score": int(item["score"]["N"])}
        #     for item in sorted_items
        # ]

        # message.reply_text(json.dumps(top_users))


application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
application.add_handler(CommandHandler("leaderboard", leaderboard))
