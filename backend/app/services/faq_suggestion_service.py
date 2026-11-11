"""Non-answering FAQ discovery: prefix + partial/fuzzy tokens + existing local embeddings."""
from collections import OrderedDict
from difflib import SequenceMatcher
import logging
import re
import time
from ..utils.normalization import normalize

logger=logging.getLogger(__name__)
STOP=set('a an the what is are how do does i my me can could should would to of for in on it this that'.split())


def terms(text):
    result=[]
    for word in re.findall(r'\w+',normalize(text)):
        if word in STOP: continue
        if len(word)>5 and word.endswith('ing'): word=word[:-3]
        elif len(word)>5 and word.endswith('ed'): word=word[:-2]
        elif len(word)>4 and word.endswith('s'): word=word[:-1]
        result.append(word)
    return result


def lexical_score(query,words):
    if not query: return 0.0
    scores=[]
    for token in query:
        best=0.0
        for word in words:
            if token==word: score=1.0
            elif len(token)>=2 and word.startswith(token): score=.9
            elif min(len(token),len(word))>=4:
                ratio=SequenceMatcher(None,token,word).ratio()
                score=ratio*.75 if ratio>=.75 else 0
            else: score=0
            best=max(best,score)
        scores.append(best)
    return sum(scores)/len(scores)


class FAQSuggestionService:
    def __init__(self,semantic,settings):
        self.semantic=semantic;self.settings=settings
        self.namespace=None;self.forms=[];self.cache=OrderedDict()

    def rebuild(self):
        namespace=self.semantic.cache_namespace
        if self.namespace==namespace: return
        self.namespace=namespace;self.cache.clear()
        self.forms=[(i,r['faq_id'],normalize(r['text']),terms(r['text'])) for i,r in enumerate(self.semantic.rows) if r['faq_id'] in self.semantic.entries]

    async def suggest(self,question,limit=5):
        version=self.semantic.kb.version if self.semantic.kb else None
        query=normalize(question)
        if len(query)<2: return {'suggestions':[],'knowledge_version':version}
        try:
            await self.semantic.refresh();self.rebuild()
            if not self.semantic.entries: return {'suggestions':[],'knowledge_version':version}
            namespace=self.namespace;key=(namespace,query,limit)
            cached=self.cache.get(key)
            if cached and cached[0]>time.monotonic():
                self.cache.move_to_end(key);return cached[1]
            qterms=terms(query);vector=None
            if len(query)>=self.settings.suggestion_semantic_min_chars and len(re.findall(r'\w+',query))>=self.settings.suggestion_semantic_min_tokens and qterms:
                vector=await self.semantic.encode_query(query)
            if self.semantic.cache_namespace!=namespace:
                self.rebuild();return {'suggestions':[],'knowledge_version':version}
            semantic_scores=self.semantic.matrix@vector if vector is not None else None
            by_faq={}
            # Short inputs avoid transformer work; scores rank suggestions, never answer confidence.
            for i,faq_id,form,words in self.forms:
                prefix=1.0 if form.startswith(query) else 0.0
                lexical=lexical_score(qterms,words)
                semantic=max(0,float(semantic_scores[i])) if semantic_scores is not None else 0.0
                if not prefix and lexical<self.settings.suggestion_lexical_min_score and semantic<self.settings.suggestion_semantic_min_similarity: continue
                score=(prefix*self.settings.suggestion_prefix_weight + lexical*self.settings.suggestion_lexical_weight
                       + semantic*self.settings.suggestion_semantic_weight)
                by_faq[faq_id]=max(score,by_faq.get(faq_id,-1))
            ranked=sorted(by_faq,key=lambda key:(-by_faq[key],self.semantic.entries[key].canonical_question.casefold(),key))[:limit]
            result={'suggestions':[{'faq_id':key,'question':self.semantic.entries[key].canonical_question,
                    'topic':self.semantic.entries[key].topic} for key in ranked],'knowledge_version':version}
            self.cache[key]=(time.monotonic()+self.settings.suggestion_cache_ttl_seconds,result)
            self.cache.move_to_end(key)
            while len(self.cache)>self.settings.suggestion_cache_items:self.cache.popitem(last=False)
            return result
        except Exception as error:
            logger.warning('FAQ suggestions unavailable (%s); chat remains available',type(error).__name__)
            return {'suggestions':[],'knowledge_version':version}
