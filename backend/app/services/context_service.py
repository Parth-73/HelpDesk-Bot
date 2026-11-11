from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ResolvedContext:
    retrieval_question: str
    user_context: list[str]
    subject: str | None


def assessment_subject(text: str) -> str | None:
    """Last explicit assessment mention; user turns take precedence over assistant hints."""
    mentions=[]
    for pattern,subject in [(r'\b(final(?: exam(?:ination)?)?|proctored exam(?:ination)?)\b','final exam'),
                            (r'\b(overall|weighted|aggregate)\b','overall score')]:
        mentions.extend((m.start(),subject) for m in re.finditer(pattern,text,re.I))
    return max(mentions)[1] if mentions else None


def resolve_conversation(question,history,relevant_context):
    users=[m.content for m in history if m.role=='user']
    context=relevant_context(question,users)
    current=assessment_subject(question)
    dependent=bool(context) or bool(re.search(r'\b(it|instead|that|same|too)\b|^what about',question,re.I))
    subject=current
    if dependent and not subject and users and re.search(r'\d+\s*%',users[-1]):
        subject=assessment_subject(users[-1])
    if dependent and not subject:
        for message in reversed(history):
            candidate=assessment_subject(message.content)
            if candidate:
                subject=candidate;break
    resolved=question
    if dependent and subject and not current:
        resolved=f'{question}\nReferenced assessment: {subject}.'
    historical = re.search(r'\b(historical|previous|old|january|version\s*1)\b', users[-1], re.I) if users else None
    last_assistant=next((m.content for m in reversed(history) if m.role=='assistant'),'')
    if dependent and (historical or last_assistant.startswith('Historical, superseded')) and not re.search(r'\b(current|latest|now)\b',question,re.I):
        resolved += '\nHistorical policy reference: Version 1.'
    # Prior assistant statements identify referents only; never become course policy evidence.
    return ResolvedContext(resolved,context,subject)
