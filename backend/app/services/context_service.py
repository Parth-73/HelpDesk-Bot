from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ResolvedContext:
    retrieval_question: str
    user_context: list[str]
    subject: str | None
    needs_clarification: bool = False


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
    assessment_context=bool(users and (assessment_subject(users[-1]) or re.search(r'\bpass(?:ing)?\b|\d+\s*%',users[-1],re.I)))
    if dependent and not subject and assessment_context:
        for message in reversed(history[-2:]):
            candidate=assessment_subject(message.content)
            if candidate:
                subject=candidate;break
    resolved=question
    if dependent and subject and not current:
        resolved=f'{question}\nReferenced assessment: {subject}.'
    # Resolve common elliptical requests using the latest exchange only. The
    # prior user turn sets scope; assistant prose supplies referents, not facts.
    previous=users[-1] if users else ''
    # Continue a short chain of references without searching through an explicit
    # intervening topic. All referents remain within this session's user turns.
    if re.fullmatch(r'\s*(?:when is it|how much|can i skip one|(?:and )?how long)\s*\??\s*',previous,re.I):
        for candidate in reversed(users[-4:-1]):
            if not re.fullmatch(r'\s*(?:when is it|how much|can i skip one|(?:and )?how long)\s*\??\s*',candidate,re.I):
                previous=candidate
                if context:context=[candidate]+context
                break
    if context and not re.search(r'\b(quiz|capstone|exam|final|fee|track|certificate|course)\b',question,re.I):
        if re.search(r'\bskip\b',question,re.I) and re.search(r'\bquiz(?:zes)?\b',previous,re.I):
            resolved += '\nReferenced subject: weekly quizzes.'
        elif re.search(r'^\s*how much\b',question,re.I):
            if re.search(r'\b(fee|cost|price|track|paid|pay)\b',previous,re.I):resolved += '\nReferenced subject: certificate track fee.'
        elif re.search(r'^\s*when\b',question,re.I):
            if re.search(r'\bcapstone\b',previous,re.I):resolved += '\nReferenced subject: capstone deadline.'
            elif re.search(r'\b(final|exam)\b',previous,re.I):resolved += '\nReferenced subject: final exam date.'
    if re.search(r'^\s*(?:and\s+)?how long\s*\??$',question,re.I) and users:
        context=users[-1:]
        if re.search(r'\b(final|exam|examination)\b',previous,re.I):resolved='What is the final exam duration?'
        elif re.search(r'\b(course|dpm.?101)\b',previous,re.I):resolved='What is the course duration?'
    # A fully specified passing question starts a new topic, even after a fee turn.
    if re.search(r'\b(pass|passing)\b',question,re.I) and not re.search(r'\b(it|that|instead|same|too)\b',question,re.I):
        context=[]
    historical = re.search(r'\b(historical|previous|old|january|version\s*1)\b', users[-1], re.I) if users else None
    last_assistant=next((m.content for m in reversed(history) if m.role=='assistant'),'')
    if dependent and (historical or last_assistant.startswith('Historical, superseded')) and not re.search(r'\b(current|latest|now)\b',question,re.I):
        resolved += '\nHistorical policy reference: Version 1.'
    # Prior assistant statements identify referents only; never become course policy evidence.
    elliptical=bool(re.search(r'^\s*(?:when is it|how much|can i skip (?:one|it)|what about it|(?:and )?how long)\s*\??$',question,re.I))
    unresolved=elliptical and resolved==question
    return ResolvedContext(resolved,context,subject,unresolved)
