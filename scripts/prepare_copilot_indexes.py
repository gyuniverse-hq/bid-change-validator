"""Explicit index preparation: approved local public sources, one shared budget."""
import argparse
from datetime import datetime,timezone
import hashlib,json,math,os,sys,time
from pathlib import Path
from uuid import UUID

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.local_copilot_evaluation import configure,STATE,save
from scripts.local_model_budget import reserve,finish


class BudgetedEmbeddings:
    available=True
    model='text-embedding-3-small'
    def __init__(self,key):
        from openai import OpenAI
        self.client=OpenAI(api_key=key,base_url='https://api.openai.com/v1',max_retries=0,timeout=45)
        self.cache=STATE/'embedding-cache-v1';self.cache.mkdir(exist_ok=True)
        self.document_calls=0;self.query_calls=0;self.cache_hits=0
    def request(self,texts,stage):
        token_upper=sum(len(t.encode()) for t in texts)+64*len(texts)
        if token_upper>100000:raise ValueError('EMBEDDING_BATCH_TOO_LARGE')
        receipt=reserve(STATE/'model-budget.json',stage,token_upper*.02/1_000_000)
        started,status,usage=time.monotonic(),'failed',None
        try:
            response=self.client.embeddings.create(model=self.model,input=texts,dimensions=1536)
            rows=sorted(response.data,key=lambda d:d.index)
            if len(rows)!=len(texts) or any(len(r.embedding)!=1536 or not all(math.isfinite(v) for v in r.embedding) for r in rows):
                raise ValueError('INVALID_EMBEDDING_RESPONSE')
            status='succeeded';usage=response.usage.model_dump()
            return [r.embedding for r in rows]
        finally:finish(STATE/'model-budget.json',receipt,status=status,elapsed_ms=round((time.monotonic()-started)*1000),usage=usage)
    def embed_documents(self,texts):
        values={};missing={}
        for text in texts:
            fingerprint=hashlib.sha256((self.model+'|1536|'+text).encode()).hexdigest()
            path=self.cache/(fingerprint+'.json')
            if path.exists():
                row=json.loads(path.read_text())
                if row['input_sha256']!=fingerprint or len(row['vector'])!=1536:raise ValueError('EMBEDDING_CACHE_CORRUPT')
                values[text]=row['vector'];self.cache_hits+=1
            else:missing[text]=(path,fingerprint)
        pending=list(missing)
        for offset in range(0,len(pending),24):
            batch=pending[offset:offset+24]
            vectors=self.request(batch,'document_embedding');self.document_calls+=1
            for text,vector in zip(batch,vectors):
                values[text]=vector;path,fingerprint=missing[text]
                save(path,{'input_sha256':fingerprint,'vector':vector})
        return [values[t] for t in texts]
    def embed_query(self,text):
        self.query_calls+=1
        return self.request([text],'query_embedding')[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--model-env',type=Path,required=True)
    args=parser.parse_args()
    identity=configure();manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    assert identity==manifest['database']
    if manifest['gates']['G2'] not in {'INPUTS_PASS','PASS'}:raise RuntimeError('G2_INPUTS_NOT_READY')
    from dotenv import dotenv_values
    key=dotenv_values(args.model_env).get('OPENAI_API_KEY')
    if not key:raise RuntimeError('MODEL_KEY_MISSING')
    from apps.api.app.database import SessionLocal
    from apps.api.app.models import PreflightCase,BidNoticeVersion
    from apps.api.app.document_rag.readiness import snapshot_sources,publish_index,inspect_index,read_passages,pack_current_passages
    from apps.api.app.document_rag.langchain_pipeline import retrieve_current
    from scripts.prepare_namwon_flow_verification import protected
    embeddings=BudgetedEmbeddings(key);rows=[]
    core=json.loads((STATE/'core-accounts.private.json').read_text(encoding='utf-8'))
    with SessionLocal() as db:
        versions={r['version_id'] for p in manifest['profiles'] for r in p['runs']}
        for account in [a for a in core if a['username'] in {'eval-j01','eval-j05','eval-j09'}]:
            case=db.get(PreflightCase,UUID(account['case_id']))
            versions.update([str(case.baseline_version_id),str(case.current_version_id)])
        for vid in sorted(versions):
            snapshot=snapshot_sources(db.get(BidNoticeVersion,UUID(vid)))
            if snapshot.source_status!='AVAILABLE':raise RuntimeError('UNVERIFIED_SOURCE: '+vid)
            before=embeddings.document_calls
            generation=publish_index(snapshot,STATE/'indexes',embeddings,expected_fingerprint=snapshot.fingerprint,max_embedding_tokens=500000)
            # Load persisted files through a fresh reader; query never builds.
            ready=inspect_index(snapshot,STATE/'indexes',embeddings)
            texts,details=retrieve_current(ready,'참가자격 및 예외, 제출서류와 기한',broad=True)
            count=embeddings.document_calls
            assert publish_index(snapshot,STATE/'indexes',embeddings,expected_fingerprint=snapshot.fingerprint,max_embedding_tokens=500000)==generation
            assert embeddings.document_calls==count
            packets=pack_current_passages(texts)
            rows.append({'version_id':vid,'status':ready.index_status,'generation':generation,'fingerprint':snapshot.fingerprint,
                'source_chunks':len(snapshot.records),'model_passages':len(packets),'chars_preserved':sum(len(t.text) for t in texts),
                'document_embedding_calls':count-before,'query':details,'repeat_build_document_calls':embeddings.document_calls-count})
            print(json.dumps({'version':vid,'status':ready.index_status,'source_chunks':len(texts),'model_passages':len(packets)},ensure_ascii=False),flush=True)
        original=db.get(PreflightCase,UUID('df1f055e-8e1e-4287-a6a1-4c46b4eaa6f5'))
        assert protected(db,original)==manifest['protected_j13_sha256']
    save(args.manifest.parent/'indexes.json',{'database':identity,'rows':rows,'embedding_cache_hits':embeddings.cache_hits,
        'document_calls':embeddings.document_calls,'query_calls':embeddings.query_calls,'protected_j13':'UNCHANGED'})
    manifest['gates']['G2']='PASS';save(args.manifest,manifest)
    print('G2=PASS')


if __name__=='__main__':main()
