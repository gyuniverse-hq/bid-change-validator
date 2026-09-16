"""Server-owned input capability and source-preserving check instructions."""
import re
from .v31_contracts import Draft,DraftClaim


def input_claim_error(claim,bundle):
    guidance=bundle.server_context.get('check_guidance',{})
    if not any(guidance.get(fid,{}).get('input_allowed') is False for fid in claim.fact_ids):
        return None
    compact=re.sub(r'\s+','',claim.text)
    # Exclude explicit negative statements before looking for an affirmative
    # invitation. This controls application capability, not legal qualification.
    compact=re.sub(r'(?:답변)?입력(?:할수없|대상이아니|불가)[^.!?。]*','',compact)
    compact=re.sub(r'답변(?:을)?(?:입력|저장|반영)하는대상(?:이|은)?아니', '', compact)
    # A bare "하" also matches "입력하거나 ... 확인할 수 없는 항목".
    # Only unambiguous invitations/affirmations are a mechanical rejection;
    # other prose still receives semantic verification against input capability.
    if re.search(r'입력(?:할수있|가능|하세요|해주|하면|할까요)|답변(?:을)?(?:입력|저장|반영)(?:해(?:주|드|도돼|도됩|볼까)|하(?:세|면|겠|실수있|도록|시면))|답변해주',compact):
        return 'INPUT_CAPABILITY_MISMATCH'
    return None


def controlled_checks(draft,bundle,criteria):
    """Use current server instructions for selected READ_CHECKS deliverables.

    These are still sent through the normal citation/coverage verification. A
    generated explanation cannot make a manual check writable. Other document,
    qualification and change claims are not replaced by templates.
    """
    selected={fid for criterion in criteria if criterion.task_kind=='READ_CHECKS' for fid in criterion.fact_ids}
    guidance=bundle.server_context.get('check_guidance',{})
    facts={f.fact_id:f for f in bundle.facts}
    selected={fid for fid in selected if fid in guidance and fid in facts and facts[fid].origin_tool=='READ_CHECKS'}
    if not selected:return draft
    # A mixed sentence promising a forbidden input may also cite a document or
    # change fact. Discard that sentence and supply the server-owned instruction;
    # the normal rubric still detects any other deliverable lost with it.
    claims=[c for c in draft.claims if (not c.fact_ids or not set(c.fact_ids)<=selected)
            and not input_claim_error(c,bundle)]
    for fid in sorted(selected):
        fact=facts[fid]
        claims.append(DraftClaim(claim_id='server-check-'+fid,text=guidance[fid]['text'],fact_ids=[fid],
                                 source_ids=fact.source_ids,speech_act='CHECK_REQUEST'))
    return Draft(claims=claims)
