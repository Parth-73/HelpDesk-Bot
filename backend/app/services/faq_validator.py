import re
from dataclasses import dataclass
from .document_service import KnowledgeBase
from .policy_resolver import resolve
from ..models.faq_schemas import ExtractedFAQ
from ..utils.normalization import digest, normalize


def whitespace(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


@dataclass
class Validation:
    status: str
    notes: list[str]
    content_hash: str


def authoritative_passages(kb: KnowledgeBase):
    return resolve(kb.passages)


def validate_faq(faq: ExtractedFAQ, kb: KnowledgeBase) -> Validation:
    current = {p.id:p for p in authoritative_passages(kb)}
    notes=[]
    review_notes=[]
    if len(set(faq.source_ids)) != len(faq.source_ids) or any(s not in current for s in faq.source_ids):
        return Validation('rejected',['invalid_or_non_authoritative_source'],digest(faq.model_dump()))
    cited=[current[s] for s in faq.source_ids]
    lines={whitespace(line) for p in cited for line in p.text.splitlines()}
    if any(whitespace(q) not in lines for q in faq.evidence_quotes):
        notes.append('fabricated_or_incomplete_evidence')
    # Every cited passage must actually contribute evidence, not merely be a real filename.
    if any(not any(whitespace(q) in {whitespace(x) for x in p.text.splitlines()} for q in faq.evidence_quotes) for p in cited):
        notes.append('unsupported_source_attribution')
    evidence=' '.join(faq.evidence_quotes)
    # Course identifiers are names, not newly asserted numeric policy thresholds.
    course_codes=set(re.findall(r'\b[A-Z]{2,}-\d+\b', ' '.join(p.text for p in current.values())))
    def numbers(value):
        for code in course_codes:
            value=re.sub(r'\b'+re.escape(code)+r'\b','',value,flags=re.I)
        return {token.strip().replace(' %','%') for token in re.findall(r'\d+(?:[.,:]\d+)*\s*%?',value)}
    if not numbers(faq.answer) <= numbers(evidence):
        if faq.question_type == 'calculation':
            review_notes.append('derived_numeric_claim_requires_manual_calculation_check')
        else:
            notes.append('unsupported_numeric_claim')
    # Strong contradictions are rejected; lexical overlap never establishes entailment.
    if any(p.topic=='passing' for p in cited) and re.search(r'\bAND\b',evidence):
        if re.search(r'\d+%\s*(?:overall\s*)?\bor\b\s*\d+%|overall(?: score)? alone is sufficient',faq.answer,re.I):
            notes.append('passing_condition_weakened')
        required = set(re.findall(r'at least\s+(\d+%)', evidence, re.I))
        if not required <= set(re.findall(r'\d+%',faq.answer)):
            notes.append('separate_passing_condition_omitted')
    if any(p.topic=='exam' for p in cited) and 'closed-book' in evidence.casefold() and re.search(r'(?:exam is|exam will be|examination is)\s+(?:now\s+)?open.book|google (?:is )?(?:allowed|permitted)',faq.answer,re.I):
        notes.append('exam_restriction_contradicted')
    if notes:
        status='rejected'
    else:
        status='needs_review'
        notes=['review_question_answer_entailment_and_each_paraphrase'] + review_notes
        if faq.requires_context:
            notes.append('context_dependent_not_runtime_eligible')
    return Validation(status,notes,digest(faq.model_dump()))


def normalize_extracted_faq(faq: ExtractedFAQ, kb: KnowledgeBase) -> ExtractedFAQ:
    """Resolve filename-only citations only when exact complete evidence identifies the passage.

    No answer text or policy claim is rewritten. Original model results remain in faq_batches.
    Partial/fabricated quotations and invented filenames remain invalid.
    """
    passages=authoritative_passages(kb)
    by_id={p.id:p for p in passages}
    resolved=[];quotes=[]
    for source in faq.source_ids:
        candidates=[by_id[source]] if source in by_id else [p for p in passages if p.metadata.filename==source]
        if not candidates:
            return faq.model_copy(deep=True)
        matching=[]
        for p in candidates:
            lines={whitespace(line):line for line in p.text.splitlines()}
            supported=[]
            for quote in faq.evidence_quotes:
                parts=[part for part in quote.splitlines() if part.strip()]
                if parts and all(whitespace(part) in lines for part in parts):
                    supported.extend(lines[whitespace(part)] for part in parts)
            if supported:
                matching.append((p,supported))
        if source not in by_id and len(matching)!=1:
            return faq.model_copy(deep=True)
        if source in by_id and not matching:
            return faq.model_copy(deep=True)
        for p,supported in matching:
            resolved.append(p.id);quotes.extend(supported)
    # Every original quote must be accounted for, never drop an unsupported fragment.
    original_parts=[whitespace(part) for q in faq.evidence_quotes for part in q.splitlines() if part.strip()]
    if not set(original_parts)<=set(whitespace(q) for q in quotes):
        return faq.model_copy(deep=True)
    return faq.model_copy(update={'source_ids':list(dict.fromkeys(resolved)), 'evidence_quotes':list(dict.fromkeys(quotes))})


def qualifier_signature(text: str) -> tuple:
    """Semantic similarity is unsafe across numeric scenarios, negation, scope or time."""
    t=text.casefold().replace("can't",'cannot').replace("isn't",'is not')
    t=re.sub(r'\bdpm[ -]?101\b','',t)
    return (tuple(re.findall(r'\d+(?:[.,:]\d+)*\s*%?',t)),
            bool(re.search(r'\b(not|no|never|cannot|without)\b',t)),
            bool(re.search(r'\b(overall|weighted|course|certif\w*|pass|passing|clear)\b',t)),
            bool(re.search(r'\b(final|exam|examination)\b',t)),
            bool(re.search(r'\b(histor\w*|previous|old|earlier|january|2025|version\s*1)\b',t)),
            bool(re.search(r'\b(if|suppose|assuming|with\s+\d)\b',t)),
            bool(re.search(r'\b(maximum|max|highest)\b',t)))


def deduplicate(faqs: list[ExtractedFAQ], embeddings=None):
    """Merge only equivalent scope, identical answer AND evidence; never let similarity choose a policy."""
    kept=[];removed=0;conflicts=set();seen={}
    for faq in faqs:
        key=normalize(faq.canonical_question)
        prior=seen.get(key)
        if prior is not None:
            if whitespace(prior.answer)!=whitespace(faq.answer) or set(prior.evidence_quotes)!=set(faq.evidence_quotes):
                conflicts.add(key)
                removed+=1
                continue
            prior.paraphrases=list(dict.fromkeys(prior.paraphrases+faq.paraphrases))[:12]
            removed+=1
            continue
        seen[key]=faq;kept.append(faq)
    if embeddings is not None and kept:
        vectors=embeddings.encode([f.canonical_question for f in kept])
        result=[];indices=[]
        for i,faq in enumerate(kept):
            duplicate=next((j for j in indices if float(vectors[i]@vectors[j])>=.97 and qualifier_signature(faq.canonical_question)==qualifier_signature(kept[j].canonical_question)
                and whitespace(faq.answer)==whitespace(kept[j].answer) and set(faq.evidence_quotes)==set(kept[j].evidence_quotes)),None)
            if duplicate is None:
                result.append(faq);indices.append(i)
            else:
                kept[duplicate].paraphrases=list(dict.fromkeys(kept[duplicate].paraphrases+[faq.canonical_question]+faq.paraphrases))[:12]
                removed+=1
        kept=result
    return kept,removed,conflicts
