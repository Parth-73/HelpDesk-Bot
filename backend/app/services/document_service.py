from dataclasses import dataclass, replace
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
import re


@dataclass(frozen=True)
class DocumentMetadata:
    filename: str
    title: str | None
    publication_date: date | None
    effective_date: date | None
    policy_version: int | None
    authority_level: str | None
    source_hash: str
    supersedes: tuple[str, ...] = ()
    encoding: str = 'utf-8'
    last_updated_date: date | None = None


@dataclass(frozen=True)
class Passage:
    id: str
    topic: str
    heading: str
    text: str
    metadata: DocumentMetadata
    authority: str = 'official'
    knowledge_version: str = ''


def parse_date(value: str) -> date | None:
    value = value.strip().rstrip('.')
    for fmt in ('%d %B %Y', '%d %b %Y', '%Y-%m-%d', '%d/%m/%Y', '%B %Y'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def topic_for(heading: str) -> str:
    h = heading.lower()
    for token, topic in [('passing', 'passing'), ('late submission', 'late'), ('capstone deadline', 'deadline'),
                         ('assessment weights', 'weights'), ('certificate tracks', 'tracks'),
                         ('technical requirements', 'technical'), ('exam rules', 'exam'),
                         ('weekly schedule', 'schedule'), ('about the course', 'overview')]:
        if token in h:
            return topic
    return re.sub(r'\W+', ' ', h).strip()


def decode(raw: bytes) -> tuple[str, str]:
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16'), 'utf-16'
    try:
        return raw.decode('utf-8-sig'), 'utf-8'
    except UnicodeDecodeError:
        # Windows smart quotes are present in many exported academic documents.
        return raw.decode('cp1252'), 'cp1252'


class KnowledgeBase:
    def __init__(self, directory: Path):
        self.documents: list[DocumentMetadata] = []
        self.passages: list[Passage] = []
        self.excluded_sections: list[str] = []
        files = sorted(directory.glob('*.txt')) if directory.is_dir() else []
        if not files:
            raise ValueError('No .txt course documents found in configured directory')
        for path in files:
            if path.is_symlink():
                raise ValueError('Document symlinks are not permitted')
            raw = path.read_bytes()
            text, encoding = decode(raw)
            def field(name: str) -> str | None:
                match = re.search(rf'^{name}:\s*(.+)$', text, re.M | re.I)
                return match.group(1).strip() if match else None
            version = re.search(r'Version\s+(\d+)', field('DOCUMENT') or '', re.I)
            effective = re.search(r'effective\s+(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{4}|\d{4}-\d{2}-\d{2})', text, re.I)
            metadata = DocumentMetadata(path.name, field('DOCUMENT'), parse_date(field('PUBLICATION DATE') or field('PUBLISHED') or ''),
                parse_date(effective.group(1)) if effective else None, int(version.group(1)) if version else None,
                field('STATUS'), sha256(raw).hexdigest(),
                tuple(re.findall(r'supersedes\s+["\u201c]?([\w.-]+\.txt)', text, re.I)), encoding, parse_date(field('LAST UPDATED') or ''))
            self.documents.append(metadata)
            if field('COURSE'):
                self.passages.append(Passage(f'{path.name}:header', 'course_identity', 'COURSE', 'COURSE: ' + field('COURSE'), metadata))
            headings = list(re.finditer(r'^\s*\d+\.\s+([^\n]+)', text, re.M))
            for index, match in enumerate(headings):
                heading = match.group(1).strip()
                # Explicitly unmoderated comments are never indexed, including injection text.
                if re.search(r'unmoderated|forum comments|raw export|student discussion', heading, re.I):
                    self.excluded_sections.append(f'{path.name}:{index+1}')
                    continue
                body = text[match.end(): headings[index+1].start() if index+1 < len(headings) else len(text)]
                # Join wrapped physical lines, retain complete bullets and their exceptions.
                paragraphs = re.split(r'\n\s*-\s+', '\n' + body.strip())
                normalized = '\n'.join(re.sub(r'\s+', ' ', p).strip(' -') for p in paragraphs if p.strip(' -\r\n'))
                if normalized:
                    self.passages.append(Passage(f'{path.name}:{index+1}', topic_for(heading), heading, normalized, metadata))
            if not headings:
                # Unknown document layouts remain traceable, but cannot silently supersede known policies.
                self.passages.append(Passage(f'{path.name}:1', topic_for(metadata.title or path.stem), metadata.title or path.stem,
                                             re.sub(r'\s+', ' ', text).strip(), metadata))
        self.version = sha256('\n'.join(f'{d.filename}:{d.source_hash}' for d in self.documents).encode()).hexdigest()
        self.passages = [replace(p, knowledge_version=self.version) for p in self.passages]
