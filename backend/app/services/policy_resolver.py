from collections import defaultdict
from datetime import date
from .document_service import Passage


class AmbiguousPolicy(ValueError):
    pass


def resolve(passages: list[Passage], today: date | None = None) -> list[Passage]:
    today = today or date.today()
    applicable = [p for p in passages if not p.metadata.effective_date or p.metadata.effective_date <= today]
    superseded = {name for p in applicable for name in p.metadata.supersedes}
    grouped: dict[str, list[Passage]] = defaultdict(list)
    for p in applicable:
        if p.metadata.filename not in superseded:
            grouped[p.topic].append(p)
    result = []
    for topic, candidates in grouped.items():
        if len(candidates) == 1:
            result.extend(candidates)
            continue
        if len({p.text for p in candidates}) == 1:
            result.append(sorted(candidates, key=lambda p: p.id)[0])
            continue
        dates = [p.metadata.effective_date or p.metadata.publication_date or p.metadata.last_updated_date for p in candidates]
        if any(d is None for d in dates):
            raise AmbiguousPolicy(f'Unresolved precedence for {topic}')
        latest = max(dates)
        winners = [p for p, d in zip(candidates, dates) if d == latest]
        if len(winners) > 1:
            versions = [p.metadata.policy_version for p in winners]
            if any(v is None for v in versions) or len(set(versions)) != len(versions):
                raise AmbiguousPolicy(f'Unresolved precedence for {topic}')
            winners = [max(winners, key=lambda p: p.metadata.policy_version)]
        result.extend(winners)
    return result
