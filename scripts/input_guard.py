# -*- coding: utf-8 -*-
"""input_guard.py: пазач на входа на монитора (ИЛЮ3 Ч2). Празен/подменен вход е шумна грешка.

Праща грешка (InputError) при: нула реда, не-списък, HTML вместо данни, ред без нужните колони.
"""
from __future__ import annotations

from typing import Any, Iterable


class InputError(RuntimeError):
    pass


def looks_like_html(text: str) -> bool:
    head = (text or "").lstrip()[:200].lower()
    return head.startswith("<!doctype") or head.startswith("<html") or head.startswith("<?xml") or head.startswith("<head") or head.startswith("<body")


def check_response_text(text: str, label: str = "вход") -> None:
    if not (text or "").strip():
        raise InputError(f"{label}: празен отговор")
    if looks_like_html(text):
        raise InputError(f"{label}: HTML вместо данни")


def validate_rows(rows: Any, required: Iterable[str], label: str = "вход") -> list:
    if isinstance(rows, str):
        check_response_text(rows, label)
        raise InputError(f"{label}: очаквах списък от редове, получих текст")
    if not isinstance(rows, list):
        raise InputError(f"{label}: очаквах списък от редове, получих {type(rows).__name__}")
    if not rows:
        raise InputError(f"{label}: нула реда")
    req = list(required)
    for i, r in enumerate(rows[:50]):
        if not isinstance(r, dict):
            raise InputError(f"{label}: ред {i} не е обект")
        missing = [c for c in req if c not in r]
        if missing:
            raise InputError(f"{label}: ред {i} без колони {missing}")
    return rows
