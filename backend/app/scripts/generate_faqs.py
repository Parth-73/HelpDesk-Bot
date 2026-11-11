import argparse
import asyncio
import json
import sys
from pathlib import Path
from ..config import Settings,ROOT
from ..database import Database
from ..services.document_service import KnowledgeBase
from ..services.gemini_service import GeminiService
from ..utils.exceptions import ServiceError
from ..services.faq_embeddings import OnnxEncoder
from ..services.faq_extractor import FAQExtractor,extraction_plan


async def run(args):
    settings=Settings();kb=KnowledgeBase(settings.course_docs_path)
    output=Path(args.output) if args.output else ROOT/'backend'/'artifacts'/'faq_candidates'
    groups,report=extraction_plan(kb,settings.gemini_model)
    if args.dry_run or (not args.enable_live and not args.report):
        output.mkdir(parents=True,exist_ok=True)
        report.update(mode='dry_run',gemini_extraction_calls=0,candidates_generated=0,duplicates_removed=0,approved=0,needs_review=0,rejected=0,
            planned_batches=len(groups),note='No generation or database writes performed. Use --enable-live to explicitly consume Gemini quota.')
        (output/'extraction_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        (output/'faq_dataset.json').write_text(json.dumps({'mode':'dry_run','knowledge_version':kb.version,'faqs':[]},indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2));return
    db=Database(settings)
    gemini=GeminiService(settings,db.increment_gemini)
    try:
        if args.report:
            if not args.snapshot: raise ValueError('--report requires --snapshot')
            extractor=FAQExtractor(db,kb,gemini,settings)
            await extractor.export(args.snapshot,output)
        else:
            if not settings.gemini_api_key.get_secret_value(): raise ValueError('Configure GEMINI_API_KEY before --enable-live')
            await db.initialize()
            encoder=await asyncio.to_thread(OnnxEncoder,settings)
            extractor=FAQExtractor(db,kb,gemini,settings,encoder)
            snapshot_id,report=await extractor.run(force=args.force)
            await extractor.export(snapshot_id,output)
            print(json.dumps(report,indent=2))
    finally:
        await gemini.close();await db.close()


def main():
    parser=argparse.ArgumentParser(description='Offline source-grounded FAQ extraction; no live calls without --enable-live')
    parser.add_argument('--dry-run',action='store_true');parser.add_argument('--enable-live',action='store_true')
    parser.add_argument('--force',action='store_true');parser.add_argument('--report',action='store_true')
    parser.add_argument('--snapshot');parser.add_argument('--output')
    args=parser.parse_args()
    try: asyncio.run(run(args))
    except ServiceError as error:
        print(f'FAQ extraction failed [{error.code}]: {error.message}', file=sys.stderr); sys.exit(1)
    except Exception as error:
        print(f'FAQ extraction failed ({type(error).__name__}). Verify configuration, model assets, database schema and provider availability.',file=sys.stderr);sys.exit(1)

if __name__=='__main__': main()
