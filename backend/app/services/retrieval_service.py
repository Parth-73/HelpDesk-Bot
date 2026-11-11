import re
from datetime import date
from rank_bm25 import BM25Okapi
from .document_service import KnowledgeBase, Passage
from .policy_resolver import resolve, AmbiguousPolicy

ABSTENTION = 'This information is not mentioned in the official DPM-101 course documents. Please contact the course team for clarification.'
CONFLICT = 'The course documents contain conflicting information, and the applicable policy cannot be determined reliably. Please contact the course team for clarification.'
ALIASES = {'commitment':'effort','earns':'earn','google':'search','speed':'internet','examinations':'exam','examination':'exam','cost':'fee','price':'fee','pay':'fee','paid':'fee','ipad':'tablet','phone':'mobile','phones':'mobile','tablets':'tablet',
           'needed':'required','need':'required','requirement':'criteria','requirements':'criteria','passing':'pass',
           'graded':'grading','grade':'grading','count':'counted','total':'overall','scores':'score','marks':'score','minimum':'threshold',
           'project':'capstone','due':'deadline','scheduled':'date','schedule':'date','allowed':'permitted',
           'allowed?':'permitted','missed':'miss','quizzes':'quiz','quiz':'quiz','penalty':'late',
           'browser':'browser','browsers':'browser','called':'name','length':'duration','last':'duration','lasts':'duration','duration':'duration','certificate':'certificate','book':'book','rules':'rule'}
STOP = set('which was were summarize summary together full name long supported happens happened what is are the a an to of for and or in on at by my i me we our you your it its that this those these they them do does did can could would should will must how much many when where who why if then than with without about please tell explain give get earn needed happens happen apply too also separately requirement course dpm 101 dpm101 there have has be been as from score required day days one two 1 2 1500 rs more less only all any into use using current student help question know want learn submit submission final proctored exam verified'.split())


def tokens(text: str) -> list[str]:
    return [ALIASES.get(w, w) for w in re.findall(r'[a-z0-9]+', text.lower())]


def relevant_context(question: str, history: list[str]) -> list[str]:
    dependent = bool(re.search(r'\b(that|it|this|those|these|they|them|too|also|instead|same)\b|^what about\b', question, re.I))
    # A question lacking an explicit subject is conservatively contextual.
    subject = re.search(r'\b(pass|passing|exam|capstone|quiz|quizzes|certificate|track|course|late|deadline|fee|grading|grade|forum|week)\b', question, re.I)
    return history[-4:] if dependent or not subject else []


class Retriever:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb
        self.superseded = {name for d in kb.documents if not d.effective_date or d.effective_date <= date.today() for name in d.supersedes}
        self.index = BM25Okapi([tokens(p.heading + ' ' + p.text) for p in kb.passages])
        self.vocabulary = {t for p in kb.passages for t in tokens(p.heading + ' ' + p.text)}

    def retrieve(self, question: str, context: list[str]) -> tuple[list[Passage], str | None]:
        q = question.lower()
        if re.search(r'\b(historical|previous policy|old policy|january|version\s*1)\b', q):
            return [], ABSTENTION
        # Questions asking for unsupported detail must not be answered from merely related passages.
        meaningful = {t for t in tokens(question) if t not in STOP and not t.isdigit()}
        unknown = meaningful - self.vocabulary - set('take taking tell explain get earn happen happen understand clarify clarify needed counted best accepted take taking test online overall weighted threshold score criteria minimum much allowed materials open closed start end available important guidelines regulations administrative assessment assessments percentages percentage breakdown weights grading policy policies deadline deadlines date dates need required teach teaches cover covers teach covering content effort time length long separate part applies apply pay paying calculator notes government photo id miss miss without same late return'.split())
        if unknown:
            return [], ABSTENTION
        combined = ' '.join(context + [question]).lower()
        topics: set[str] = set()
        def match(pattern: str) -> bool: return bool(re.search(pattern, combined))
        if match(r'pass|threshold|distinction|minimum.*score'): topics.add('passing')
        if match(r'late|grace|penalt|miss.*quiz|quiz.*miss'): topics.add('late')
        if match(r'capstone|deadline|due|important dates'): topics.add('deadline')
        if match(r'weight|graded|grading|assessment|percent.*quiz'): topics.add('weights')
        if match(r'fee|cost|price|track|upgrade|audit'): topics.add('tracks')
        if match(r'ipad|phone|mobile|tablet|technical|internet|browser|computer|laptop|mbps'): topics.add('technical')
        if match(r'exam|closed.book|open.book|calculator|photo|aadhaar|passport|\bid\b'): topics.add('exam')
        if match(r'quiz'): topics.update(('weights', 'late'))
        if match(r'effort|commitment|hours|weekly schedule|doubt|forum|teaching assistant|\bta\b'): topics.add('schedule')
        if match(r'teach|cover|about the course|content|topics|course.*(?:duration|long|length|last)|(?:duration|long|length).*course'): topics.add('overview')
        if match(r'course.*name|name.*course|full.*name|called'): topics.add('course_identity')
        if not topics:
            return [], ABSTENTION
        candidates = [p for p in self.kb.passages if p.topic in topics and p.metadata.filename not in self.superseded]
        try:
            selected = resolve(candidates)
        except AmbiguousPolicy:
            return [], CONFLICT
        if not selected:
            return [], ABSTENTION
        evidence = ' '.join(p.text.lower() for p in selected)
        # Specific qualifiers cannot be inferred from a general policy.
        for qualifier in ('maximum', 'refund', 'scholarship', 'extension', 'reschedule', 'retake', 'appeal'):
            if qualifier in q and qualifier not in evidence:
                return [], ABSTENTION
        scores = dict(zip([p.id for p in self.kb.passages], self.index.get_scores(tokens(combined))))
        return sorted(selected, key=lambda p: (-scores[p.id], p.id))[:8], None

