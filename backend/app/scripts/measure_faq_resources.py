"""Measure the actual ONNX inference path, without loading credentials or calling Gemini."""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path
import psutil
from ..config import Settings
from ..services.faq_embeddings import OnnxEncoder


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--queries',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();settings=Settings();process=psutil.Process()
    baseline=process.memory_info().rss/1024**2;start=time.perf_counter();encoder=OnnxEncoder(settings)
    load=time.perf_counter()-start;loaded=process.memory_info().rss/1024**2
    queries=json.loads(Path(args.queries).read_text(encoding='utf-8-sig'))
    times=[];peak=loaded
    for question in queries:
        start=time.perf_counter();encoder.encode([question]);times.append((time.perf_counter()-start)*1000)
        peak=max(peak,process.memory_info().rss/1024**2)
    report={'model':settings.faq_embedding_model,'revision':settings.faq_embedding_revision,'baseline_rss_mb':baseline,
        'loaded_rss_mb':loaded,'observed_peak_rss_mb':peak,'model_load_seconds':load,'query_count':len(times),
        'median_latency_ms':statistics.median(times),'max_latency_ms':max(times),'torch_imported':'torch' in sys.modules,
        'within_configured_memory_budget':peak<=settings.faq_memory_limit_mb,'scope':'Standalone CPU ONNX process, not a full hosted load test. RSS sampled after each inference.'}
    Path(args.output).write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))

if __name__=='__main__': main()
