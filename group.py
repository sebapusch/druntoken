import math
import os
from os import path
from sqlite3 import Connection, connect

from errors.bet_error import BetError
from dtypes import GroupInfo, BetResult


class Group:
    data_path: str

    def __init__(
            self,
            tg_chat_id: int | None = None,
            connection: Connection | None = None,
    ):

        if connection is None:
            if tg_chat_id is None:
                raise ValueError('You must provide either a database connection or a chat id')
            db_path = path.abspath(path.join(Group.data_path, f'{tg_chat_id}.db'))
            if not os.access(db_path, os.R_OK):
                raise ValueError(f'Group does not exist.')
            connection = connect(db_path)

        group_info = connection.execute('SELECT id, tg_id, description FROM group_info').fetchone()

        self.connection = connection
        self.group_info: GroupInfo = {
            'group_id': group_info[0],
            'tg_chat_id': group_info[1],
            'description': group_info[2],
        }

    @staticmethod
    def create_group(chat_id: int, description: str) -> 'Group':
        db_path = path.join(Group.data_path, f'{chat_id}.db')

        if path.exists(db_path):
            raise ValueError(f'Path \'{db_path}\' already exists')

        connection = connect(db_path)
        Group._init_database(connection, chat_id, description)

        return Group(connection=connection)

    def add_member(self, tg_id: int, name: str, tokens: int = 10000) -> bool:
        if self.has_member(tg_id):
            return False

        self.connection.execute(
            'INSERT INTO members (tg_id, name, tokens) VALUES (?, ?, ?)',
            (tg_id, name, tokens))
        self.connection.commit()

        return True

    def all_in(self, tg_user_id: int) -> int:
        return self.get_tokens(tg_user_id)

    def get_tokens(self, tg_id: int) -> int | None:
        member = self.connection.execute(
            'SELECT tokens FROM members WHERE tg_id = ?',
            (tg_id,)
        ).fetchone()

        if member is None:
            return None

        return int(member[0])

    def suggest(self, suggestion: str) -> None:
        self.connection.execute("INSERT INTO suggestions (text) VALUES (?)", (suggestion,))
        self.connection.commit()

    def get_suggestions(self) -> list[str]:
        suggestions = self.connection.execute('SELECT text FROM suggestions').fetchall()
        return [s[0] for s in suggestions]

    def has_member(self, tg_id: int) -> bool:
        return (self.connection
                .execute('SELECT * FROM members WHERE tg_id = ?', (tg_id,))
                .fetchone() is not None)

    def place_bet(self, member_tg_id: int, tg_message_id: int, amount: int) -> int:
        member = self.connection.execute(
            'SELECT id, tokens FROM members WHERE tg_id = ?',
            (member_tg_id,)
        ).fetchone()

        if member is None:
            raise BetError('Please join to place a bet')

        poll = self.connection.execute(
            'SELECT id FROM polls WHERE tg_message_id = ?',
            (tg_message_id,)
        ).fetchone()

        if poll is None:
            raise BetError('No such poll')

        poll_id, = poll

        tokens = int(member[1])
        if tokens < amount:
            raise BetError(f'Insufficient tokens ({tokens})')

        cursor = self.connection.cursor()
        bet = cursor.execute(
            'SELECT id FROM bets WHERE member_id = ? AND poll_id = ?',
            (member[0], poll_id)
        ).fetchone()
        if bet is not None:
            raise BetError('You already placed a bet for this poll!')

        try:
            self.connection.execute(
                'INSERT INTO bets (member_id, amount, poll_id) VALUES (?, ?, ?)',
                (member[0], amount, poll_id)
            )
            new_member_tokens = tokens - amount
        except Exception as e:
            self.connection.rollback()
            raise BetError(e)
        else:
            self.connection.commit()

        return new_member_tokens

    def select_option(self, member_tg_id: int, tg_poll_id: int, tg_index: int):
        option = self.connection.execute(
            'SELECT poll_options.id, poll_options.tg_index, polls.id, polls.tg_poll_id as tg_poll_id '
            'FROM poll_options '
            'JOIN polls ON poll_options.poll_id = polls.id '
            'WHERE tg_poll_id = ? AND poll_options.tg_index = ?',
            (tg_poll_id, tg_index)
        ).fetchone()

        if option is None:
            raise BetError('Invalid poll or option. Make sure you placed your bet.')

        member = self.connection.execute(
            'SELECT id, tokens FROM members WHERE tg_id = ?',
            (member_tg_id,)
        ).fetchone()

        if member is None:
            raise BetError('Please join to place a bet!')

        cursor = self.connection.cursor()
        cursor.execute(
            'UPDATE bets SET poll_option_id = ? '
            'WHERE poll_id = ? AND member_id = ? ',
            (option[0], option[2], member[0])
        )

        if cursor.rowcount == 0:
            self.connection.rollback()
            raise BetError('You have no bets open for this poll!')

        self.connection.commit()

    def store_poll(self, poll: dict, tg_poll_id: int, tg_message_id: int) -> int:
        cursor = self.connection.cursor()

        cursor.execute(
            'INSERT INTO polls (tg_poll_id, tg_message_id, text) VALUES (?, ?, ?)',
            (tg_poll_id, tg_message_id, poll['text'])
        )
        poll_id = cursor.lastrowid

        cursor.executemany(
            'INSERT INTO poll_options (poll_id, text, tg_index, rating) VALUES (?, ?, ?, ?)',
            [
                (poll_id, o['text'], i, o['rating'])
                for i, o in enumerate(poll['options'])
            ]
        )
        self.connection.commit()

        return cursor.lastrowid

    def close_poll(self, tg_poll_id: int, correct_tg_index: int) -> (list[BetResult], str):
        bets = self.connection.execute(
            'SELECT amount, member_id, polls.tg_poll_id as tg_poll_id, poll_options.tg_index as tg_index, '
            'members.name as member_name, members.tokens as tokens, polls.id as poll_id '
            'FROM bets '
            'JOIN poll_options ON bets.poll_option_id = poll_options.id '
            'JOIN polls ON poll_options.poll_id = polls.id '
            'JOIN members ON bets.member_id = members.id '
            'WHERE tg_poll_id = ?',
            (tg_poll_id,)
        ).fetchall()

        correct, wrong = [], []
        winnable, total_bet = 0, 0

        if len(bets) > 0:
            poll_id = bets[0][6]
        else:
            return [], "Nessuna scommessa piazzata"

        for bet in bets:
            if int(bet[3]) == correct_tg_index:
                correct.append(bet)
                total_bet += bet[0]
            else:
                wrong.append(bet)
                winnable += bet[0]

        if winnable == 0:
            self.connection.execute('UPDATE bets SET open = 0 WHERE poll_id = ?', (poll_id, ))
            self.connection.commit()
            return [], "Non c'è nulla da vincere"

        feedback: list[BetResult] = []
        cursor = self.connection.cursor()
        try:
            for bet in correct:
                win_factor = int(bet[0]) / total_bet
                win = math.floor(win_factor * winnable)
                new_tokens = int(bet[5]) + win
                cursor.execute('UPDATE members SET tokens = ? WHERE id = ?', (new_tokens, bet[1]))
                feedback.append({
                    'member_id': bet[1],
                    'member_name': bet[4],
                    'win': win,
                    'tokens': new_tokens
                })
            for bet in wrong:
                new_tokens = int(bet[5]) - int(bet[0])
                cursor.execute('UPDATE members SET tokens = ? WHERE id = ?', (new_tokens, bet[1]))
                feedback.append({
                    'member_id': bet[1],
                    'member_name': bet[4],
                    'win': -int(bet[0]),
                    'tokens': new_tokens
                })

            cursor.execute('UPDATE bets SET open = 0 WHERE poll_id = ?', (poll_id, ))
        except Exception as e:
            self.connection.rollback()
            raise BetError(e)
        else:
            self.connection.commit()

        return feedback, "All good"

    @staticmethod
    def _init_database(connection: Connection, chat_id: int, description: str) -> None:
        connection.execute('CREATE TABLE IF NOT EXISTS group_info ('
                           'id INTEGER PRIMARY KEY,'
                           'description TEXT,'
                           'tg_id INTEGER)')
        connection.execute('CREATE TABLE IF NOT EXISTS members('
                           'id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
                           'tg_id INTEGER NOT NULL,'
                           'name TEXT,'
                           'tokens INTEGER NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS suggestions('
                           'id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
                           'text TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS polls('
                           'id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
                           'tg_poll_id INTEGER NOT NULL,'
                           'tg_message_id INTEGER NOT NULL,'
                           'text TEXT NOT NULL,'
                           'open TINYINT NOT NULL DEFAULT 1)')
        connection.execute('CREATE TABLE IF NOT EXISTS poll_options('
                           'id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
                           'tg_index INTEGER NOT NULL,'
                           'text TEXT NOT NULL,'
                           'rating INTEGER NOT NULL,'
                           'poll_id INTEGER NOT NULL,'
                           'FOREIGN KEY (poll_id) REFERENCES polls(id))')
        connection.execute('CREATE TABLE IF NOT EXISTS bets('
                           'id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
                           'amount INTEGER NOT NULL,'
                           'open TINYINT NOT NULL DEFAULT 1,'
                           'member_id INTEGER NOT NULL,'
                           'poll_id INTEGER NOT NULL,'
                           'poll_option_id INTEGER NULLABLE,'
                           'FOREIGN KEY (member_id) REFERENCES members(id),'
                           'FOREIGN KEY (poll_id) REFERENCES polls(id),'
                           'FOREIGN KEY (poll_option_id) REFERENCES poll_options(id))')

        connection.execute('INSERT INTO group_info (id, tg_id, description) VALUES (0, ?, ?)',
                           (chat_id,description))
        connection.commit()
