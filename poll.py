from os import path
from sqlite3 import connect
from typing import Optional


class Poll:
    data_path: str

    def __init__(self):
        self.connection = connect(path.join(Poll.data_path, 'polls.db'))
        self.connection.execute('CREATE TABLE IF NOT EXISTS polls('
                                'id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
                                'tg_poll_id INTEGER NOT NULL,'
                                'tg_chat_id INTEGER NOT NULL)')
        self.connection.commit()

    def store(self, tg_poll_id: int, tg_chat_id: int) -> None:
        self.connection.execute(
            'INSERT INTO polls (tg_poll_id, tg_chat_id) VALUES (?, ?)',
            (tg_poll_id, tg_chat_id)
        )
        self.connection.commit()

    def get_tg_chat_id(self, tg_poll_id: int) -> Optional[int]:
        res = self.connection.execute(
            'SELECT tg_chat_id FROM polls WHERE tg_poll_id=?',
            (tg_poll_id,)
        ).fetchone()

        return res[0] if res is not None else None

