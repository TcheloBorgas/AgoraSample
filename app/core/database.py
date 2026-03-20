"""Persistência: armazenamento em memória (sem MongoDB).

O caminho com pymongo está comentado abaixo. Para voltar a usar Mongo:
1. pip install pymongo
2. Descomentar o bloco Mongo e apontar get_db para lá
3. Definir USE_MONGO=true e MONGO_URI no ambiente
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.config import settings

# --- MongoDB (desativado para deploy simples só com Gemini / sem Atlas) ---
# from pymongo import MongoClient
# from pymongo.database import Database
#
# _mongo_client: MongoClient | None = None
#
#
# def _get_mongo_database() -> Database:
#     global _mongo_client
#     if _mongo_client is None:
#         _mongo_client = MongoClient(settings.mongo_uri)
#     return _mongo_client[settings.mongo_db_name]


def _matches(doc: dict[str, Any], q: dict[str, Any]) -> bool:
    return all(doc.get(k) == v for k, v in q.items())


def _get_path(doc: dict[str, Any], parts: list[str]) -> Any:
    cur: Any = doc
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _set_path(doc: dict[str, Any], parts: list[str], value: Any) -> None:
    cur = doc
    for p in parts[:-1]:
        nxt = cur.setdefault(p, {})
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _inc_path(doc: dict[str, Any], parts: list[str], delta: int | float) -> None:
    cur = doc
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    k = parts[-1]
    cur[k] = (cur.get(k) or 0) + delta


class _MemoryCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = list(rows)
        self._sort_key: str | None = None
        self._sort_dir = -1
        self._lim: int | None = None

    def sort(self, key: str, direction: int = -1) -> _MemoryCursor:
        self._sort_key = key
        self._sort_dir = direction
        return self

    def limit(self, n: int) -> _MemoryCursor:
        self._lim = n
        return self

    def __iter__(self) -> Any:
        rows = self._rows
        if self._sort_key:
            rows = sorted(
                rows,
                key=lambda r: r.get(self._sort_key) or datetime.min,
                reverse=(self._sort_dir < 0),
            )
        if self._lim is not None:
            rows = rows[: self._lim]
        return iter(rows)


class MemoryCollection:
    def __init__(self) -> None:
        self._docs: list[dict[str, Any]] = []

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self._docs:
            if _matches(doc, query):
                return dict(doc)
        return None

    def insert_one(self, doc: dict[str, Any]) -> None:
        self._docs.append(dict(doc))

    def find(self, query: dict[str, Any]) -> _MemoryCursor:
        rows = [d for d in self._docs if _matches(d, query)]
        return _MemoryCursor(rows)

    def update_one(self, filter_q: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
        idx = next((i for i, d in enumerate(self._docs) if _matches(d, filter_q)), None)
        if idx is None:
            if not upsert:
                return
            new_doc: dict[str, Any] = {k: v for k, v in filter_q.items()}
            self._apply_update_ops(new_doc, update)
            self._docs.append(new_doc)
            return
        self._apply_update_ops(self._docs[idx], update)

    @staticmethod
    def _apply_update_ops(doc: dict[str, Any], update: dict[str, Any]) -> None:
        if "$set" in update:
            for path, val in update["$set"].items():
                parts = path.split(".")
                _set_path(doc, parts, val)
        if "$inc" in update:
            for path, delta in update["$inc"].items():
                parts = path.split(".")
                _inc_path(doc, parts, delta)
        if "$addToSet" in update:
            for path, raw in update["$addToSet"].items():
                parts = path.split(".")
                items: list[Any]
                if isinstance(raw, dict) and "$each" in raw:
                    items = list(raw["$each"])
                else:
                    items = [raw]
                cur = _get_path(doc, parts)
                if cur is None:
                    _set_path(doc, parts, [])
                    cur = _get_path(doc, parts)
                if not isinstance(cur, list):
                    continue
                for item in items:
                    if item not in cur:
                        cur.append(item)


@dataclass
class MemoryDatabase:
    _collections: dict[str, MemoryCollection] = field(default_factory=dict)

    def __getitem__(self, name: str) -> MemoryCollection:
        if name not in self._collections:
            self._collections[name] = MemoryCollection()
        return self._collections[name]


_memory_db = MemoryDatabase()


def get_db() -> MemoryDatabase:
    """Base em RAM (suficiente para testar UI + Gemini no Render sem Mongo)."""
    if settings.use_mongo:
        raise RuntimeError("USE_MONGO=true requer pymongo reativado em app/core/database.py")
    return _memory_db
