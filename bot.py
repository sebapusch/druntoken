import math
from logging import warning

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update, CallbackQuery
from telegram.ext import CallbackContext, Application, CommandHandler, PollAnswerHandler, CallbackQueryHandler

from errors.bet_error import BetError
from group import Group
from poll import Poll
from prompt_handler import PromptHandler

COMMANDS = {
    'help': ('help', 'Stampa questa lista'),
    'suggest': ('suggest', '<suggerimento:stringa> Aggiungi un suggerimento'),
    'bet': ('bet', '<quantità:numero|"all-in"> Piazza una scommessa'),
    'close': ('close', '<opzione:numero> Chiudi un sondaggio'),
    'create': ('create', 'Crea un nuovo database locale gruppo'),
    'tokens': ('tokens', 'Mostra il tuo numero di token'),
    'generate': ('generate', '<suggerimento(opzionale):stringa> Genera un nuovo sondaggio')
}


def bot(application: Application, data_path: str, prompt_path: str) -> None:
    Group.data_path = data_path
    Poll.data_path = data_path

    prompter = PromptHandler(prompt_path)
    poll = Poll()
    join_button = InlineKeyboardMarkup([[
        InlineKeyboardButton('Entra', callback_data='join')
    ]])

    def clean(update: Update, cmd: str) -> str:
        return update.effective_message.text.replace('/' + COMMANDS[cmd][0], '').strip()

    def cmd_help(cmd: str) -> str:
        return '/' + COMMANDS[cmd][0] + ' ' + COMMANDS[cmd][1]

    async def get_amount(update: Update, group: Group) -> int | None:
        amount_str = clean(update, 'bet')
        if amount_str == 'all-in':
            amount = group.all_in(update.effective_user.id)
            if amount == 0:
                await update.message.reply_text(
                    await prompter.prompt(
                        'error',
                        {'error': 'Cercando di andare all-in nonostante non abbia più token.'}
                    ))
                return None
        else:
            try:
                amount = int(amount_str)
            except Exception:
                await update.message.reply_text(
                    await prompter.prompt(
                        'error',
                        {'error': 'Inserendo un valore non numerico'}
                    ))
                return None

        if amount <= 0:
            await update.message.reply_text(
                await prompter.prompt(
                    'error',
                    {'error': 'Inserendo un numero di token minore o uguale a zero.'}
                ))
            return None

        return amount

    async def select_option(update: Update, context: CallbackContext) -> None:
        tg_poll_id = int(update.poll_answer.poll_id)
        tg_chat_id = poll.get_tg_chat_id(tg_poll_id)
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
                await prompter.prompt(
                    'error',
                    {
                        'error': 'Non piazzando una scommessa prima di selezionare l\'opzione',
                    }))

    async def help_handler(update: Update, _: CallbackContext) -> None:
        await update.message.reply_text(
            '\n'.join([cmd_help(cmd) for cmd in COMMANDS])
        )

    async def create(update: Update, _: CallbackContext):
        try:
            Group.create_group(update.effective_chat.id, '')
        except ValueError as e:
            await update.message.reply_text(f'Errore durante la creazione del gruppo: {e}')
            return

        await update.message.reply_text('Gruppo creato correttamente!', reply_markup=join_button)

    async def join(update: Update, _: CallbackContext):
        query = update.callback_query
        group = Group(tg_chat_id=int(update.effective_chat.id))
        user_name = query.from_user.full_name

        if not group.add_member(int(query.from_user.id), user_name):
            message = await prompter.prompt('error', {
                'error': f'{user_name} sta provando a rientrare nonostante sia già un membro'
            })
        else:
            message = await prompter.prompt('user_joined', {'user': user_name})

        await update.effective_chat.send_message(message)

    async def suggest(update: Update, _: CallbackContext) -> None:
        group = Group(tg_chat_id=update.effective_chat.id)
        suggestion = clean(update, 'suggest')
        if suggestion == "":
            await update.message.reply_text('Nessun suggerimento ricevuto. Utilizzo: ' + cmd_help('suggest'))
            return

        group.suggest(suggestion)

        await update.message.reply_text('Ok! Ho aggiunto il suggerimento')

    async def tokens(update: Update, _: CallbackContext) -> None:
        group = Group(tg_chat_id=update.effective_chat.id)
        tokens_ = group.get_tokens(update.effective_user.id)

        if tokens_ is None:
            await update.message.reply_text('Non sei ancora un membro', reply_markup=join_button)
        else:
            await update.message.reply_text(f'Hai ancora {tokens_} token')

    async def generate(update: Update, context: CallbackContext) -> None:
        chat_id = update.effective_chat.id
        group = Group(tg_chat_id=chat_id)

        generated = await prompter.json_prompt('generate', {
            'suggestion': clean(update, 'generate') or None
        })
        message = await context.bot.send_poll(
            is_anonymous=False,
            chat_id=chat_id,
            question=generated['text'],
            options=[option['text'] for option in generated['options']],
        )

        group.store_poll(generated, int(message.poll.id), message.id)
        poll.store(int(message.poll.id), chat_id)

    async def bet(update: Update, _: CallbackContext) -> None:
        tg_chat_id = update.effective_chat.id
        poll_message = update.effective_message.reply_to_message
        if poll_message is None:
            await update.message.reply_text('Per favore seleziona un sondaggio.')
            return

        tg_message_id = poll_message.id
        group = Group(tg_chat_id=tg_chat_id)
        amount = await get_amount(update, group)

        try:
            tokens_ = group.place_bet(update.effective_user.id, int(tg_message_id), amount)
        except BetError as e:
            await update.message.reply_text(await prompter.prompt('error', {'error': str(e)}))
        else:
            await update.message.reply_text(
                f'Scommessa piazzata correttamente!'
                f'\nSeleziona l\'opzione che ritieni corretta.'
                f'\nHai ancora {tokens_} token a disposizione.')

    async def close(update: Update, ctx: CallbackContext) -> None:
        tg_chat_id = update.effective_chat.id
        poll_message = update.effective_message.reply_to_message

        try:
            correct_option_index = int(clean(update, 'close'))
        except:
            await update.message.reply_text(
                await prompter.prompt('error', {'error': 'Inserendo un valore non numerico.'})
            )
            return

        if poll_message is None:
            await update.message.reply_text('Please select a poll.')
            return

        group = Group(tg_chat_id=tg_chat_id)
        tg_poll_id = int(poll_message.poll.id)
        closed_poll = group.get_poll(tg_poll_id)
        if poll is None:
            await update.message.reply_text(
                await prompter.prompt('error', {'error': 'Chiudendo un non-sondaggio'})
            )
        await ctx.bot.stop_poll(tg_chat_id, poll_message.id)
        result, message = group.close_poll(tg_poll_id, int(correct_option_index))

        outcome = ', '.join([
            res['member_name'] + ' ha vinto ' if res['win'] else ' has perso ' + str(math.fabs(res['win'])) + ' token'
            for res in result
        ])

        await update.message.reply_text(
            await prompter.prompt('poll_result', {
                'outcome': outcome,
                'poll': closed_poll['text']
            })
        )

        application.add_handler(CommandHandler(COMMANDS['help'], help_handler))
        application.add_handler(CommandHandler(COMMANDS['create'], create))
        application.add_handler(CommandHandler(COMMANDS['tokens'], tokens))
        application.add_handler(CommandHandler(COMMANDS['suggest'], suggest))
        application.add_handler(CommandHandler(COMMANDS['generate'], generate))
        application.add_handler(CommandHandler(COMMANDS['bet'], bet))
        application.add_handler(CommandHandler(COMMANDS['close'], close))

        application.add_handler(PollAnswerHandler(select_option))
        application.add_handler(CallbackQueryHandler(join, 'join'))

        application.run_polling()
