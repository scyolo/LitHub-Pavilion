"""API 依赖：DB 会话。"""
from app.db import get_db as _get_db


def get_db():
    yield from _get_db()
