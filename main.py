import math
from logging import warning
from os import environ

from openai import AsyncOpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler, PollAnswerHandler

from errors.bet_error import BetError
from group import Group
from poll import Poll
from poll_generator import PollGenerator

load_dotenv()

DATA_PATH = environ.get('DATA_PATH')
BOT_TOKEN = environ.get('BOT_TOKEN')

COMMANDS = {
    'close': 'close'
}

Group.data_path = DATA_PATH
Poll.data_path = DATA_PATH

poll_handler = Poll()


def join_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton('Entra', callback_data='join')
    ]])


async def create(update: Update, _: CallbackContext):
    try:
        Group.create_group(update.effective_chat.id, '')
    except ValueError as e:
        await update.message.reply_text(f'Errore durante la creazione del gruppo: {e}')
        return

    await update.message.reply_text('Gruppo creato correttamente!', reply_markup=join_button())


async def join(update: Update, _: CallbackContext):
    query = update.callback_query
    group = Group(tg_chat_id=int(update.effective_chat.id))
    user_id = int(query.from_user.id)
    user_name = query.from_user.full_name

    if not group.add_member(user_id, user_name):
        message = f'{user_name} è già un membro.'
    else:
        message = f'{user_name} aggiunto correttamente!'

    await update.effective_chat.send_message(message)


async def suggest(update: Update, _: CallbackContext) -> None:
    group = Group(tg_chat_id=update.effective_chat.id)
    suggestion = update.message.text.replace("/suggest", "").strip("")
    if suggestion == "":
        await update.message.reply_text('Nessun suggerimento ricevuto. Utilizzo: /suggest {suggerimento}')
        return

    group.suggest(suggestion)

    await update.message.reply_text('Ok! Ho aggiunto il suggerimento')


async def tokens(update: Update, _: CallbackContext) -> None:
    group = Group(tg_chat_id=update.effective_chat.id)
    tokens_ = group.get_tokens(update.effective_user.id)

    if tokens_ is None:
        await update.message.reply_text('Non sei ancora un membro', reply_markup=join_button())
    else:
        await update.message.reply_text(f'Hai ancora {tokens_} token')


async def generate(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id

    group = Group(tg_chat_id=chat_id)
    generator = PollGenerator(group)

    suggestion = update.message.text.replace("/generate ", "").strip()
    if suggestion == "":
        suggestion = None

    generated = await generator.generate(AsyncOpenAI(), suggestion)
    message = await context.bot.send_poll(
        is_anonymous=False,
        chat_id=chat_id,
        question=generated['text'],
        options=[option['text'] for option in generated['options']],
    )

    group.store_poll(generated, int(message.poll.id), message.id)
    poll_handler.store(int(message.poll.id), chat_id)


async def generate_error_message(client: AsyncOpenAI, error: str) -> str:
    response = await client.chat.completions.create(
        messages=[{
            'role': 'system',
            'content': f'Un utente ha provato a rompere l\'applicativo nel seguente modo: {error}. Sgridalo in modo ridicolo e fagli capire l\'errore. Accusalo in modo esagerato di razzismo, fascimo, misoginia o simili.',
        }],
        model="gpt-3.5-turbo-0125",
    )

    return response.choices[0].message.content


async def generate_poll_message(client: AsyncOpenAI, result: str, feedback: str) -> str:
    response = await client.chat.completions.create(
        messages=[{
            'role': 'system',
            'content': f'Lo stato di chiusura del sondaggio è andato così: {result}. Questi sono i risultati: {feedback}. Riporta il risultato in modo idiota ma preciso.',
        }],
        model="gpt-3.5-turbo-0125",
    )

    return response.choices[0].message.content


async def bet(update: Update, _: CallbackContext) -> None:
    tg_chat_id = update.effective_chat.id
    poll_message = update.effective_message.reply_to_message
    if poll_message is None:
        await update.message.reply_text('Per favore seleziona un sondaggio.')
        return

    tg_message_id = poll_message.id
    group = Group(tg_chat_id=tg_chat_id)
    try:
        amount_str = update.effective_message.text.replace('/bet', '').strip()
        if amount_str == 'all-in':
            amount = group.all_in(update.effective_user.id)
        else:
            amount = int(amount_str)
    except:
        await update.message.reply_text(
            await generate_error_message(AsyncOpenAI(), 'Inserendo un valore non numerico'))
        return

    if amount <= 0:
        await update.message.reply_text(
            await generate_error_message(AsyncOpenAI(), 'Inserendo un minore o uguale a zero'))
        return

    try:
        tokens_ = group.place_bet(update.effective_user.id, int(tg_message_id), amount)
    except BetError as e:
        await update.message.reply_text(await generate_error_message(AsyncOpenAI(), str(e)))
    else:
        await update.message.reply_text(
            f'Scommessa piazzata correttamente!'
            f'\nSeleziona l\'opzione che ritieni corretta.'
            f'\nHai ancora {tokens_} token a disposizione.')


async def select_option(update: Update, context: CallbackContext) -> None:
    tg_poll_id = int(update.poll_answer.poll_id)
    tg_chat_id = poll_handler.get_tg_chat_id(tg_poll_id)
    if tg_chat_id is None:
        return warning(f'Received poll id \'{tg_poll_id}\' with no corresponding group, ignoring')

    group = Group(tg_chat_id=tg_chat_id)

    try:
        group.select_option(
            update.poll_answer.user.id,
            tg_poll_id,
            update.poll_answer.option_ids[0]
        )
    except BetError:
        await context.bot.send_message(
            group.group_info['tg_chat_id'],
            await generate_error_message(AsyncOpenAI(), 'Non piazzando una scommessa prima di selezionare l\'opzione, per l\'ennesima volta'),
        )


async def close(update: Update, _: CallbackContext) -> None:
    tg_chat_id = update.effective_chat.id
    poll_message = update.effective_message.reply_to_message

    correct_option_index = update.effective_message.text.replace(f'/{COMMANDS["close"]}', '')

    if poll_message is None:
        await update.message.reply_text('Please select a poll.')
        return

    group = Group(tg_chat_id=tg_chat_id)
    tg_poll_id = int(poll_message.poll.id)
    # await context.bot.stop_poll(tg_chat_id, poll_message.id)
    result, message = group.close_poll(tg_poll_id, int(correct_option_index))

    msg = ''
    for res in result:
        win = res['win']
        tk = res['tokens']
        verb = 'ha vinto' if res['win'] > 0 else 'ha perso'
        msg += f'{res["member_name"]} {verb} {math.fabs(win):0} token. {tk} tokens rimanenti.\n'

    await update.message.reply_text(await generate_poll_message(AsyncOpenAI(), result, msg))


async def instructions(update: Update, _) -> None:
    await update.message.reply_text(
        '/create create a new group\n'
        '/tokens print the amount of tokens in your possession\n'
        '/suggest <suggerimento> create new poll suggestion\n'
        '/generate generate a new poll\n'
        '/bet <quantità> place a bet on a given poll\n'
        '/close close the given poll'
    )


def main():
    # todo: validate data path
    # todo: error handler

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler('help', instructions))
    app.add_handler(CommandHandler('create', create))
    app.add_handler(CommandHandler('tokens', tokens))
    app.add_handler(CommandHandler('suggest', suggest))
    app.add_handler(CommandHandler('generate', generate))
    app.add_handler(CommandHandler('bet', bet))

    app.add_handler(CommandHandler('close', close))

    app.add_handler(PollAnswerHandler(select_option))

    app.add_handler(CallbackQueryHandler(join, 'join'))

    app.run_polling()


if __name__ == "__main__":
    main()
