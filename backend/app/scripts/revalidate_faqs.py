import argparse,asyncio,sys
from ..config import Settings,ROOT
from ..database import Database
from ..services.document_service import KnowledgeBase
from ..services.faq_repository import FAQRepository
from ..services.faq_extractor import FAQExtractor

async def run(snapshot):
    settings=Settings();db=Database(settings);kb=KnowledgeBase(settings.course_docs_path)
    try:
        repo=FAQRepository(db);await repo.revalidate_candidates(snapshot,kb)
        await FAQExtractor(db,kb,None,settings).export(snapshot,ROOT/'backend'/'artifacts'/'faq_candidates')
        print(await repo.report(snapshot))
    finally:await db.close()
if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Revalidate unreviewed candidates without Gemini calls; preserve original batch results')
    parser.add_argument('--snapshot',required=True)
    try:asyncio.run(run(parser.parse_args().snapshot))
    except Exception as error:
        print(f'Revalidation failed ({type(error).__name__}); snapshot must be current, inactive and unreviewed.',file=sys.stderr);sys.exit(1)
