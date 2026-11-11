"""Hand-reviewed examples ONLY for mocked tests/calibration, never a production FAQ generator."""
from app.models.faq_schemas import ExtractedFAQ
from app.services.faq_validator import authoritative_passages


def examples(kb):
    by_topic={p.topic:p for p in authoritative_passages(kb)}
    passing=by_topic['passing'];late=by_topic['late'];exam=by_topic['exam'];technical=by_topic['technical']
    course=by_topic['course_identity'];deadline=by_topic['deadline'];tracks=by_topic['tracks']
    rows=[
        ('What percentage do I need to pass?', ['How much do I need to score to pass DPM-101?'],passing,0,'factual'),
        ('How much must I score in the final examination?', ['What is the minimum final exam score?'],passing,0,'factual'),
        ('Can I pass with 70% overall and 35% in the final?', ['Can I get certified with 70% overall and 35% on the final exam?'],passing,0,'conditional'),
        ('Are late submissions accepted?', ['Can I submit the capstone two days late?'],late,0,'exception'),
        ('Is the final exam open-book?', ['Can I use Google during the examination?'],exam,3,'misunderstanding'),
        ('Can I take the exam on an iPad?', ['Can I use my mobile phone to take the proctored exam?'],technical,0,'eligibility'),
        ('What is the course name?', ['What is this course called?'],course,0,'factual'),
        ('What is the deadline for the capstone?', ['When is the Capstone Product Case due?'],deadline,0,'deadline'),
        ('How much does the Verified Certificate track cost?', ['What does the certificate cost?'],tracks,1,'factual'),
        ('When is the final exam scheduled?', ['What date is the proctored final examination?'],exam,0,'deadline'),
    ]
    return [ExtractedFAQ(canonical_question=q,paraphrases=para,answer=p.text.splitlines()[line],source_ids=[p.id],
        evidence_quotes=[p.text.splitlines()[line]],topic=p.topic,question_type=kind) for q,para,p,line,kind in rows]


def calibration(entries):
    lookup={e.canonical_question:str(e.faq_id) for e in entries}
    questions=[
        ('What score must I achieve to pass the course?','What percentage do I need to pass?','paraphrase'),
        ('How much must I score in my final examination?','How much must I score in the final examination?','scope'),
        ('Can I pass with 70% overall and 35% in the final?','Can I pass with 70% overall and 35% in the final?','conditional'),
        ('Is the final exam open-book?','Is the final exam open-book?','paraphrase'),
        ('Can I take the exam on an iPad?','Can I take the exam on an iPad?','paraphrase'),
        ('What is the deadline for the capstone?','What is the deadline for the capstone?','paraphrase'),
        ('Do I not have to pass the final examination?',None,'negation'),
        ('What was the passing threshold in January 2026?',None,'historical'),
        ('Who won the cricket match last night?',None,'off_topic'),
        ('Can I pass with 70% overall and 45% in the final?',None,'conditional'),
        ('Tell me about everything',None,'ambiguous'),
        ('What is the maximum final exam score?',None,'scope'),
    ]
    return [dict(question=q,expected_faq_id=lookup[target] if target else None,category=category) for q,target,category in questions]
