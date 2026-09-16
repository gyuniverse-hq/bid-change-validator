"""A fixed output slot for every sentence and every frozen acceptance item.

This constrains transport identity/completeness, never whether evidence supports
a sentence. The existing mechanical and semantic acceptance gates still decide.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, create_model
from .v31_contracts import Verdicts


class SentenceReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['SUPPORTED', 'CONTRADICTED', 'INSUFFICIENT']
    reason: str
    observed_act: Literal['ASSERTION', 'CHECK_REQUEST', 'ASSUMPTION']


def fixed_verification_contract(body):
    claims = body.get('claims', [])
    siblings = body.get('supported_siblings', [])
    criteria = body.get('acceptance', [])
    aliases = {row['claim_id']: f'C{i+1}' for i, row in enumerate(claims)}
    aliases.update({row['claim_id']: f'S{i+1}' for i, row in enumerate(siblings)})
    criterion_refs = {row['criterion_id']: f'K{i+1}' for i, row in enumerate(criteria)}
    refs = {**aliases, **criterion_refs}
    def replace(value):
        if isinstance(value, str): return refs.get(value, value)
        if isinstance(value, list): return [replace(v) for v in value]
        if isinstance(value, dict): return {k: replace(v) for k, v in value.items()}
        return value
    sentence_map = create_model('EverySentenceReview', __config__={'extra':'forbid'},
        **{f'C{i+1}': (SentenceReview, ...) for i in range(len(claims))})
    ref_type = Literal[tuple(aliases.values())] if aliases else str
    coverage_row = create_model('FrozenCriterionReview', __config__={'extra':'forbid'},
        status=(Literal['MET','MISSING','UNAVAILABLE'], ...),
        claim_ids=(list[ref_type], Field(max_length=len(aliases))), reason=(str, ...))
    criterion_map = create_model('EveryCriterionReview', __config__={'extra':'forbid'},
        **{f'K{i+1}': (coverage_row, ...) for i in range(len(criteria))})
    schema = create_model('CompleteVerificationResponse', __config__={'extra':'forbid'},
        verdicts=(sentence_map, ...), criteria=(criterion_map, ...))
    def restore(result):
        value = result.model_dump()
        reverse = {v:k for k,v in aliases.items()}
        return Verdicts(
            verdicts=[dict(claim_id=row['claim_id'], **value['verdicts'][f'C{i+1}'])
                      for i,row in enumerate(claims)],
            criteria=[dict(criterion_id=row['criterion_id'],
                **{**value['criteria'][f'K{i+1}'], 'claim_ids':[
                    reverse[ref] for ref in value['criteria'][f'K{i+1}']['claim_ids']]})
                for i,row in enumerate(criteria)])
    return replace(body), schema, restore
