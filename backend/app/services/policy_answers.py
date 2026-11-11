"""Small deterministic decisions grounded in parsed current policy, never hard-coded policy values."""
import re
from .cache_service import Answer
from .policy_resolver import resolve,AmbiguousPolicy


def historical_question(question):
    return bool(re.search(r'\b(historical|previous|old|earlier|january|version\s*1)\b',question,re.I))


class PolicyAnswers:
    def __init__(self,kb):
        self.kb=kb
        self.superseded={name for d in kb.documents for name in d.supersedes}

    def current(self,topic):
        try:return resolve([p for p in self.kb.passages if p.topic==topic and p.metadata.filename not in self.superseded])
        except AmbiguousPolicy:return []

    def answer(self,text,passages):
        sources=tuple(sorted({(p.metadata.filename,p.metadata.source_hash) for p in passages}))
        return Answer(text,sources,origin='deterministic')

    def historical(self,question):
        if not historical_question(question):return None
        topic='late' if re.search(r'late|grace|penalt',question,re.I) else 'deadline' if re.search(r'capstone|deadline|due',question,re.I) else 'passing' if re.search(r'pass|score|threshold|distinction',question,re.I) else None
        old=[p for p in self.kb.passages if p.metadata.filename in self.superseded and p.topic==topic]
        if not old:return None
        return self.answer('Historical, superseded policy — this is not the current rule.\n\n'+'\n\n'.join(p.text for p in old),old)

    def decide(self,question,context,subject):
        historical=self.historical(question)
        if historical is not None:return historical
        if historical_question(question):return None
        q=question.casefold();prior=' '.join(context).casefold()
        if re.search(r'\b(course|dpm.?101)\b',q) and re.search(r'full.*name|name|called',q):
            p=self.current('course_identity')
            if p:return self.answer(p[0].text.removeprefix('COURSE: '),p)
        passing=self.current('passing')
        line=next((line for p in passing for line in p.text.splitlines() if re.search(r'\bAND\b',line) and 'overall' in line.casefold()),None)
        minima=re.findall(r'at least\s+(\d+(?:\.\d+)?)%',line or '',re.I)
        if len(minima)<2:return None
        overall_min,final_min=map(float,minima[:2])
        fmt=lambda number:f'{number:g}%'
        if re.search(r'\b(pay|paid|fee|payment)\b',q+' '+prior) and re.search(r'\b(certificate|certified|certification)\b',q) and re.search(r'\b(automatically|enough|guarantee|mean|alone|will|get|eligible)\b',q):
            tracks=self.current('tracks')
            return self.answer('Payment alone does not establish certification eligibility. '+line,passing+tracks)
        # User-supplied scores are scenario inputs, not claims about official thresholds.
        values=re.findall(r'(\d+(?:\.\d+)?)\s*%',q)
        scenario=bool(values) and bool(re.search(r'\b(if|score|scored|get|got|with|instead)\b',q))
        domain=bool(re.search(r'pass|certif|final|overall',q+' '+prior)) or subject is not None
        if scenario and not subject and re.search(r'\b(it|that|instead)\b',q):
            return Answer('Do you mean your overall weighted score or your separate final-exam score?',(),origin='deterministic')
        if scenario and domain and not re.search(r'\b(audit|refund|scholarship|exception|medical)\b',q):
            scores={}
            for m in re.finditer(r'(\d+(?:\.\d+)?)\s*%\s*(?:in\s+|on\s+|for\s+)?(?:the\s+)?(overall|final|exam)',q):
                scores['overall score' if m.group(2)=='overall' else 'final exam']=float(m.group(1))
            if len(values)==1 and subject:
                scores.setdefault(subject,float(values[0]))
            if not scores:
                return Answer('Do you mean your overall weighted score or your separate final-exam score?',(),origin='deterministic')
            if any(value<0 or value>100 for value in scores.values()):
                return Answer('Please give percentage scores between 0 and 100.',(),origin='deterministic')
            failures=[]
            if scores.get('final exam',100)<final_min:failures.append(f"the final-exam score of {fmt(scores['final exam'])} is below {fmt(final_min)}")
            if scores.get('overall score',100)<overall_min:failures.append(f"the overall score of {fmt(scores['overall score'])} is below {fmt(overall_min)}")
            requirements=f'You must meet both requirements: at least {fmt(overall_min)} overall AND at least {fmt(final_min)} separately in the final examination.'
            if failures:return self.answer('No. '+' and '.join(failures)+'. '+requirements,passing)
            if len(scores)==2:return self.answer('Yes. Those scores meet both stated passing thresholds. '+requirements,passing)
            return self.answer('That score meets the threshold for that assessment, but does not by itself establish that you pass. '+requirements,passing)
        if re.search(r'exam',q) and re.search(r'open.book|google',q) and re.search(r'ignore|disregard|system|coordinator|announced|claims|update',q):
            exam=self.current('exam')
            if exam:return self.answer('The supplied claim does not override the official exam rules.\n\n'+'\n'.join(p.text for p in exam),exam)
        if re.search(r'exam',q) and re.search(r'moved|changed|postponed|rescheduled',q):
            exam=self.current('exam')
            schedule=next((line for p in exam for line in p.text.splitlines() if line.startswith('Exam Date:')),None)
            proposed=re.search(r'(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)',q)
            if schedule and proposed:
                official=re.search(r'(\d{1,2})\s+(\w+)\s+\d{4}',schedule)
                mismatch=official and (int(proposed.group(1)),proposed.group(2))!=(int(official.group(1)),official.group(2).casefold())
                prefix='No. That claimed date change is not supported by the official documents. ' if mismatch else 'The official documents state: '
                return self.answer(prefix+schedule,exam)
        return None
