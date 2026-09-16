"""Keep every reservation; settle only successful calls with known token usage.

Rates are the same conservative evaluation assumptions already used at reserve
time. No cache discount is applied. This ledger is not provider billing.
Failed, pending, legacy and missing-usage calls keep their full reservation.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


@contextmanager
def ledger_transaction(path):
    path = Path(path)
    lock = path.with_suffix('.lock')
    deadline = time.monotonic() + 5
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError('EVALUATION_BUDGET_LOCKED')
            time.sleep(.02)
    try:
        os.close(fd)
        ledger = json.loads(path.read_text(encoding='utf-8'))
        yield ledger
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,path)
    finally:
        lock.unlink()


def reserve(path,stage,amount):
    from apps.api.app.copilot.model_gateway import BudgetExceeded
    with ledger_transaction(path) as ledger:
        if amount <= 0 or ledger['reserved_estimate_usd'] + amount > min(16.03,ledger['cap_estimate_usd']):
            raise BudgetExceeded('LOCAL_EVALUATION_BUDGET_EXHAUSTED')
        ledger['reserved_estimate_usd'] += amount
        index = len(ledger['calls'])
        ledger['calls'].append({'stage':stage,'status':'reserved','reserved_estimate_usd':amount,
                               'time':datetime.now(timezone.utc).isoformat()})
        return index


def finish(path,index,*,status,elapsed_ms,usage=None):
    with ledger_transaction(path) as ledger:
        ledger['calls'][index].update(status=status,elapsed_ms=elapsed_ms,usage=usage)
        _settle(ledger)


def _settle(ledger):
    credit=0.0
    known=0
    for call in ledger['calls']:
        reserved=call.get('reserved_estimate_usd')
        usage=call.get('usage')
        if call.get('status')!='succeeded' or not isinstance(reserved,(int,float)) or not isinstance(usage,dict):
            continue
        prompt=usage.get('prompt_tokens');completion=usage.get('completion_tokens')
        if call.get('stage') in {'document_embedding','query_embedding'}:
            if type(prompt) is not int or prompt<0:continue
            spent=prompt*.02/1_000_000
        elif call.get('stage') in {'plan','parse_answer','generate','validate','repair','revalidate',
                                  'document_extract','document_verify','document_repair','document_revalidate'}:
            if type(prompt) is not int or type(completion) is not int or min(prompt,completion)<0:continue
            spent=(prompt*.20+completion*1.20)/1_000_000
        else:continue
        # A surprisingly high measured cost increases the commitment rather
        # than hiding an underestimate. Historical call entries stay intact.
        credit+=reserved-spent;known+=1
    previous=ledger.get('settled_credit_usd',0.0)
    delta=credit-previous
    if abs(delta)>1e-12:
        ledger['reserved_estimate_usd']-=delta
        ledger['settled_credit_usd']=credit
        ledger.setdefault('settlements',[]).append({'time':datetime.now(timezone.utc).isoformat(),
            'delta_usd':delta,'cumulative_credit_usd':credit,'successful_calls_with_known_usage':known,
            'rates_per_million':{'prompt':.20,'completion':1.20,'embedding':.02},
            'note':'Same reserve-time rate assumptions; no cache discount; failed/pending/unknown usage not credited.'})


def settle(path):
    with ledger_transaction(path) as ledger:
        _settle(ledger)
        return {'net_commitment_estimate_usd':ledger['reserved_estimate_usd'],
                'gross_reservations_usd':ledger['reserved_estimate_usd']+ledger.get('settled_credit_usd',0),
                'settled_credit_usd':ledger.get('settled_credit_usd',0), 'cap_estimate_usd':ledger['cap_estimate_usd']}
