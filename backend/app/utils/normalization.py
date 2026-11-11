import hashlib
import json
import re
import unicodedata

PROMPT_VERSION = 'extractive-hybrid-context-v4'


def normalize(text: str) -> str:
    # Preserve internal punctuation (e.g. 1.5 versus 15, and negation).
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text).casefold()).strip().rstrip('?!., ')


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def cache_key(question: str, context: list[str], kb: str, model: str) -> str:
    return digest([normalize(question), [normalize(q) for q in context], kb, PROMPT_VERSION, model])
