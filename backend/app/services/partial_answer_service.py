"""Return complete supported portions with an explicit boundary on their scope."""
import re
from .cache_service import Answer
from .retrieval_service import broad_learning


def supported_portion(question,passages,kb):
    selected=[];boundary=None
    if broad_learning(question):
        selected=[p for p in passages if p.topic=='overview']
        if selected:
            boundary='These are the documented course topics; they do not establish a detailed examination syllabus or a study plan.'
            # Preserve both supported facets of a compound question. A syllabus
            # match must not silently discard an explicitly requested deadline.
            if re.search(r'\b(deadlines?|due)\b',question,re.I):
                if re.search(r'\b(final|exam|examination)\b',question,re.I) and not re.search(r'\bcapstone\b',question,re.I):
                    # Exam date is documented; a separate exam submission
                    # deadline is not. Do not substitute the capstone deadline.
                    boundary+=' A separate final-exam submission deadline is not specified.'
                else:
                    selected=[p for p in passages if p.topic=='deadline']+selected
            if re.search(r'\bprepar',question,re.I):
                boundary+=' If you mean preparation for a particular assessment, please say which one.'
    elif re.search(r'\bfail(?:s|ed|ing)?\b',question,re.I) and re.search(r'\b(final|exam)\b',question,re.I):
        selected=[p for p in passages if p.topic=='passing']
        if selected:
            boundary='This specifies certification eligibility. It does not specify a retake or remediation procedure.'
    if not selected:return None
    text='\n\n'.join(p.text for p in selected)+'\n\n'+boundary
    sources=tuple(sorted({(p.metadata.filename,p.metadata.source_hash) for p in selected}))
    return Answer(text,sources,origin='deterministic')
