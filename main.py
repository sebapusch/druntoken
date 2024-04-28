from os import environ

from dotenv import load_dotenv
from telegram.ext import Application

from bot import bot


def main():
    load_dotenv()
    app = Application.builder().token(environ.get('BOT_TOKEN')).build()

    bot(app, environ.get('DATA_PATH'), environ.get('PROMPT_PATH'))


if __name__ == "__main__":
    main()
