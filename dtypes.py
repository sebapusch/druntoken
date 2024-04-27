from typing import TypedDict


class GroupInfo(TypedDict):
    tg_chat_id: int
    group_id: int


class BetResult(TypedDict):
    member_id: int
    member_name: str
    win: int
    tokens: int
