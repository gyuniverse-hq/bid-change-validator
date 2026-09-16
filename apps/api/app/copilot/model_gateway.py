"""One bounded model attempt per call; retries and usage are never hidden."""
import json
import os
from time import monotonic

DOCUMENT_BATCHES = 12
DOCUMENT_REPAIR_BATCHES = 3
DOCUMENT_CALLS = 2 * (DOCUMENT_BATCHES + DOCUMENT_REPAIR_BATCHES)
LARGE_INPUT_BYTES = 240000
LARGE_OUTPUT_TOKENS = 6000
QUALITY_STAGES = {'generate', 'validate', 'repair', 'revalidate'}


class BudgetExceeded(RuntimeError):
    pass


class ModelGateway:
    def __init__(self, *, client=None, model=None, deadline_seconds=45):
        self.started = monotonic()
        self.deadline = self.started + deadline_seconds
        self.model = model or os.getenv('COPILOT_MODEL') or os.getenv('OPENAI_MODEL_DEFAULT') or 'gpt-5.6-luna'
        self.client = client
        self.calls = []
        self.enabled = True
        self.allow_large_context = True
        self.large_context = False
        self.fact_citations = True

    def call_limits(self, stage):
        return (LARGE_INPUT_BYTES, LARGE_OUTPUT_TOKENS) if self.large_context and stage in QUALITY_STAGES else (16000, 3000)

    def call_cost_upper(self, stage):
        input_bound, output_bound = self.call_limits(stage)
        return (input_bound * .20 + output_bound * 1.20) / 1_000_000

    @property
    def available(self):
        return self.client is not None or bool(os.getenv('OPENAI_API_KEY'))

    def remaining(self):
        return max(0, self.deadline - monotonic())

    def prepare_call(self,stage,system,body,schema):
        from ..document_rag.langchain_pipeline import structured_messages
        payload=json.dumps(body,ensure_ascii=False,default=str)
        prompt=structured_messages(system,payload,examples=stage in {'generate','repair'})
        upper=len((''.join(str(m.content) for m in prompt.to_messages())+json.dumps(schema.model_json_schema())).encode('utf-8'))+512
        if stage in QUALITY_STAGES and self.allow_large_context and upper>16000:
            self.large_context=True
        return prompt,upper

    def call(self, stage, system, body, schema):
        if not self.enabled:
            raise RuntimeError('MODEL_PROCESSING_DISABLED')
        if stage.startswith('integration_') and sum(c['stage'].startswith('integration_') for c in self.calls) >= 12:
            raise BudgetExceeded('INTEGRATION_BUDGET')
        if stage.startswith('group_') and sum(c['stage'].startswith('group_') for c in self.calls) >= 32:
            raise BudgetExceeded('PRODUCT_GROUP_BUDGET')
        if stage in {'document_extract', 'document_verify', 'document_repair', 'document_revalidate'}:
            if not getattr(self, 'document_review', False) or sum(c['stage'].startswith('document_') for c in self.calls) >= DOCUMENT_CALLS:
                raise BudgetExceeded('DOCUMENT_REVIEW_BUDGET')
        quality = [c for c in self.calls if c['stage'] in {'generate', 'validate', 'repair', 'revalidate'}]
        if (stage in {'generate', 'validate', 'repair', 'revalidate'} and len(quality) >= 4) or self.remaining() < 1:
            raise BudgetExceeded('TURN_BUDGET')
        if stage == 'plan' and any(c['stage'] == 'plan' for c in self.calls):
            raise BudgetExceeded('PLAN_BUDGET')
        if stage == 'parse_answer' and any(c['stage'] == 'parse_answer' for c in self.calls):
            raise BudgetExceeded('ANSWER_PARSE_BUDGET')
        if stage == 'repair' and self.remaining() < 8:
            raise BudgetExceeded('REPAIR_AND_VALIDATION_BUDGET')
        from ..document_rag.langchain_pipeline import invoke_structured, PROMPT_VERSION
        restore = lambda result: result
        from .v31_contracts import Verdicts
        if schema is Verdicts and 'claims' in body:
            from .verification_contract import fixed_verification_contract
            body, schema, restore = fixed_verification_contract(body)
            system += '\n출력 verdicts는 C 번호별 필수 객체이고 criteria는 K 번호별 필수 객체이다. 각 슬롯을 빠짐없이 평가한다. S 번호는 이미 검증한 문장으로 criteria 근거로만 선택한다. 상태는 근거에 따라 판단하며 누락 내용을 MET으로 만들지 않는다.'
        prompt_value,upper=self.prepare_call(stage,system,body,schema)
        # UTF-8 bytes is a conservative token upper bound; include the response schema.
        input_limit, output_limit = self.call_limits(stage)
        if upper > input_limit:
            raise BudgetExceeded('INPUT_BUDGET')
        if not self.available:
            raise RuntimeError('MODEL_UNAVAILABLE')
        if self.client is None:
            from openai import OpenAI
            self.client = OpenAI(max_retries=0)
        entry = {'stage': stage, 'model': self.model, 'input_token_upper_bound': upper,
                 'reserved_cost_upper_usd': self.call_cost_upper(stage), 'output_token_limit': output_limit,
                 'usage': None, 'status': 'started', 'pipeline': 'langchain',
                 'prompt_version': PROMPT_VERSION, 'few_shot': stage in {'generate', 'repair'}}
        self.calls.append(entry)
        start = monotonic()
        try:
            response = invoke_structured(self.client, model=self.model, prompt=prompt_value, schema=schema,
                                         output_limit=output_limit, timeout=self.remaining())
            entry['usage'] = response.usage.model_dump() if response.usage else None
            if self.remaining() <= 0:
                raise BudgetExceeded('LATE_MODEL_RESULT')
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise RuntimeError('MODEL_REFUSAL')
            entry['status'] = 'succeeded'
            return restore(schema.model_validate(parsed))
        except Exception as error:
            entry['status'] = 'failed'
            entry['error'] = type(error).__name__
            raise
        finally:
            entry['elapsed_ms'] = round((monotonic() - start) * 1000)

    def embed_query(self, text):
        if not self.enabled or not self.available or self.remaining() < 1 or len(text.encode('utf-8')) > 8000:
            raise BudgetExceeded('QUERY_EMBEDDING_BUDGET')
        if sum(c['stage'] == 'query_embedding' for c in self.calls) >= 3:
            raise BudgetExceeded('QUERY_EMBEDDING_CALLS')
        if self.client is None:
            from openai import OpenAI
            self.client = OpenAI(max_retries=0)
        entry = {'stage': 'query_embedding', 'model': 'text-embedding-3-small', 'usage': None, 'status': 'started'}
        self.calls.append(entry)
        start = monotonic()
        try:
            response = self.client.with_options(max_retries=0, timeout=self.remaining()).embeddings.create(
                model=entry['model'], input=[text])
            entry['usage'] = response.usage.model_dump() if response.usage else None
            if self.remaining() <= 0:
                raise BudgetExceeded('LATE_QUERY_EMBEDDING')
            entry['status'] = 'succeeded'
            return response.data[0].embedding
        except Exception as error:
            entry.update(status='failed', error=type(error).__name__)
            raise
        finally:
            entry['elapsed_ms'] = round((monotonic() - start) * 1000)

    def embed_documents(self, texts):
        raise RuntimeError('Chat cannot embed documents')
