"""Private operator review and atomic activation. No public ingestion endpoints."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from ..config import Settings,ROOT
from ..database import Database
from ..models.faq_schemas import ReviewFile
from ..services.document_service import KnowledgeBase
from ..services.faq_repository import FAQRepository
from ..services.faq_embeddings import OnnxEncoder
from ..services.faq_index import build_index


async def run(args):
    settings=Settings();kb=KnowledgeBase(settings.course_docs_path);db=Database(settings);repo=FAQRepository(db)
    try:
        snapshot_id=args.snapshot
        if args.review:
            decisions=ReviewFile.model_validate_json(Path(args.review).read_text(encoding='utf-8-sig'))
            if snapshot_id and snapshot_id!=decisions.snapshot_id: raise ValueError('Review snapshot differs from --snapshot')
            snapshot_id=decisions.snapshot_id
            await repo.review(decisions,kb)
            print('Review decisions stored; no index activated yet.')
        if args.activate:
            if not snapshot_id or not args.calibration: raise ValueError('--activate needs --snapshot and --calibration')
            snapshot=await repo.snapshot(snapshot_id)
            if not snapshot or snapshot.knowledge_version!=kb.version: raise ValueError('Snapshot is absent or outdated')
            entries=[e for e in await repo.entries(snapshot_id) if e.verification_status=='approved']
            cases=json.loads(Path(args.calibration).read_text(encoding='utf-8-sig'))
            encoder=await asyncio.to_thread(OnnxEncoder,settings)
            index=await asyncio.to_thread(build_index,entries,encoder,kb.version,cases)
            await repo.activate(snapshot_id,kb,index)
            output=ROOT/'backend'/'artifacts'/'faq_candidates';output.mkdir(parents=True,exist_ok=True)
            (output/'semantic_index.json').write_text(json.dumps(index),encoding='utf-8')
            print('Approved FAQ index activated atomically. Runtime workers refresh within FAQ_REFRESH_SECONDS.')
        if not snapshot_id: raise ValueError('Supply --snapshot or --review')
        print(json.dumps(await repo.report(snapshot_id),indent=2))
    finally: await db.close()


def main():
    parser=argparse.ArgumentParser(description='Apply explicit operator reviews and activate a validated FAQ index')
    parser.add_argument('--snapshot');parser.add_argument('--review');parser.add_argument('--calibration');parser.add_argument('--activate',action='store_true')
    try: asyncio.run(run(parser.parse_args()))
    except Exception as error:
        print(f'FAQ review/activation failed ({type(error).__name__}); verify snapshot, reviewed hashes, evidence and calibration labels.',file=sys.stderr);sys.exit(1)

if __name__=='__main__': main()
