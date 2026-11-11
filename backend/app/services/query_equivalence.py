"""Conservative, corpus-specific intent proof; embeddings only rank candidates.

Unknown wording goes to retrieval, never to an approximate response-cache hit.
No policy values live here: this module classifies questions, not answers.
"""
import re
from ..utils.normalization import normalize

VERSION = 'bounded-intents-v1'

# Closed vocabulary deliberately excludes unsupported modifiers such as extra,
# scientific, refund, questions, instructors, retakes and accommodations.
WORDS = set('''what whats is are was were do does did can could may must should would
will i we my our a an the to of for and in on at by how much many long when which
it this that need needs needed required requirements requirement conditions criteria
minimum score marks scores percentage pass passing clear earn get receive obtain
certificate verified track course dpm final exam examination proctored test duration
length minutes time allotted take takes last lasts run weeks online program
capstone product case project submission deadline due date submit submitted hand
turn in handed need have has be been before until with without notes note use using
consult bring allowed allow permitted open closed book during into weekly quiz
quizzes miss missed skip one penalty late submissions accepted grace period work
still cost costs price fee pay study learn learning topics topic cover covers covered
syllabus curriculum teach taught will graded grading assessment assessments weights
weight weighting each component count counted breakdown equipment technical
requirements phone mobile ipad tablet computer laptop taking sit schedule scheduled
day does us we up rules policy current official only separate separately overall
weighted aggregate threshold necessary needed me you your needed about please tell
explain want know available hows whats thats s dont cannot not no never instead or materials
referenced subject assessment deadline format end of from week time examination
'''.split())


def clean(text):
    value = normalize(text).replace('’', "'")
    value = re.sub(r"\bwhat's\b", 'what is', value)
    value = re.sub(r'\bdpm[ -]?101\b', 'dpm', value)
    return value


def intent(text):
    """Return one bounded answer intent or None; no semantic guess on residuals."""
    q = clean(text)
    if re.search(r'\b(was|were|did)\b',q):return None
    words = set(re.findall(r'[a-z]+', q))
    if words - WORDS or re.search(r'\d|\b(if|not|no|never|cannot|without|instead|previous|old|historical|earlier|maximum)\b', q):
        # 'without penalty' is a fixed quiz-policy phrase, not logical negation.
        stripped = re.sub(r'without (?:a )?penalty', '', q) if re.search(r'\b(quiz|quizzes)\b',q) and re.search(r'\b(miss|missed|skip)\b',q) else q
        if words - WORDS or re.search(r'\d|\b(if|not|no|never|cannot|without|instead|previous|old|historical|earlier|maximum)\b', stripped):
            return None
    exam = bool(re.search(r'\b(exam|examination|final|proctored|test)\b', q))
    course = bool(re.search(r'\b(course|dpm|program)\b', q))
    capstone = bool(re.search(r'\b(capstone|product case|project)\b', q))
    quiz = bool(re.search(r'\b(quiz|quizzes)\b', q))
    if re.search(r'\bone\b|\ba day\b',q) and not (quiz and re.search(r'\b(miss|missed|skip)\b',q)):
        return None
    found = set()
    duration = bool(re.search(r'how long|how many (?:minutes|weeks)|\b(duration|length|allotted)\b', q))
    if duration:
        if exam and course:return None
        if exam and not capstone and not quiz: found.add('exam_duration')
        elif course and not capstone and not quiz: found.add('course_duration')
    date = bool(re.search(r'\b(when|deadline|due|date|scheduled)\b', q))
    if date and capstone: found.add('capstone_deadline')
    if date and exam and not capstone: found.add('exam_date')
    if re.search(r'\b(pass|passing|clear)\b|earn.*certificate|(?:need|requirements|conditions).*certificate', q):
        if not re.search(r'\b(overall|weighted|aggregate|separate|separately|final|exam|examination)\b', q): found.add('passing')
        elif exam and not re.search(r'\b(overall|weighted|aggregate)\b',q): found.add('final_passing')
        elif not exam and re.search(r'\b(overall|weighted|aggregate)\b',q): found.add('overall_passing')
    elif re.search(r'\b(score|marks|threshold)\b',q) and exam and re.search(r'\b(minimum|threshold|need|needed|required|must|should)\b',q): found.add('final_passing')
    if re.search(r'\b(notes?|book|materials)\b', q) and not quiz and not capstone:
        if course and not exam and not re.search(r'course notes?',q):return None
        found.add('exam_materials')
    if re.search(r'\b(miss|missed|skip)\b', q) and quiz and not capstone: found.add('quiz_miss')
    if re.search(r'\b(late|grace)\b', q) and not exam: found.add('late_submission')
    if re.search(r'\b(cost|costs|price|fee|pay)\b', q) and re.search(r'\b(certificate|verified|track)\b', q): found.add('fee')
    if re.search(r'\b(study|learn|learning|topics|topic|syllabus|curriculum|cover|covers|covered)\b', q) and not exam and not quiz and not capstone: found.add('overview')
    if re.search(r'\b(graded|grading|weight|weights|weighting|breakdown)\b|each assessment.*count', q): found.add('weights')
    # Device compatibility and the full technical checklist are related but
    # not answer-equivalent: leave those to approved exact FAQs/document RAG.
    return next(iter(found)) if len(found) == 1 else None


def equivalent(left, right):
    """Same recognized scope AND preserved qualifiers; cosine alone is insufficient."""
    a, b = intent(left), intent(right)
    if a is None or a!=b:return False
    # The same late/weight policy may mention several components, but a cached
    # response to one component is not evidence of equivalence to another.
    if a in {'late_submission','weights'}:
        def scope(value):
            q=clean(value)
            return (bool(re.search(r'\b(quiz|quizzes)\b',q)),
                    bool(re.search(r'\b(capstone|project|product case)\b',q)),
                    bool(re.search(r'\b(final|exam|examination)\b',q)))
        if scope(left)!=scope(right):return False
    return True


RETRIEVAL_FORMS = {
    'exam_duration':'What is the final exam duration?',
    'course_duration':'What is the course duration?',
    'capstone_deadline':'When is the capstone deadline?',
    'passing':'What are the passing requirements?',
    'final_passing':'What is the minimum final exam score to pass?',
    'overall_passing':'What is the minimum overall weighted score to pass?',
    'exam_materials':'What are the closed-book final exam rules for notes?',
    'quiz_miss':'How many weekly quizzes can I miss?',
    'late_submission':'What is the late submission policy?',
    'fee':'What is the verified certificate track fee?',
    'overview':'What topics are covered in the course?',
    'weights':'What are the assessment grading weights?',
    'technical':'What are the final exam technical requirements?',
}
