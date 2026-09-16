"""LangChain integration over the existing version-pinned store and model budget.

No independent credential, retry, embedding build, judgment or write path lives
here. The product gateway owns time/cost; the source adapter owns scope checks.
"""
import json
from time import monotonic
from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda
from pydantic import Field

PROMPT_VERSION = 'copilot-grounded-fewshot-v1'


class CurrentVersionRetriever(BaseRetriever):
    readiness: Any
    broad: bool = False
    details: dict = Field(default_factory=dict)

    def _get_relevant_documents(self, query, *, run_manager):
        from .readiness import read_passages
        started = monotonic()
        records, details = read_passages(self.readiness, query, broad=self.broad)
        self.details = {**details, 'retriever': 'langchain.CurrentVersionRetriever',
                        'retrieval_ms': round((monotonic() - started) * 1000)}
        return [Document(page_content=r.text, metadata=r.metadata.model_dump(mode='json')) for r in records]


def retrieve_current(readiness, question, *, broad=False):
    from .store import DocumentChunkRecord
    retriever = CurrentVersionRetriever(readiness=readiness, broad=broad)
    documents = retriever.invoke(question, config={'run_name': 'copilot.current_version_retrieval'})
    return [DocumentChunkRecord(text=d.page_content, metadata=d.metadata) for d in documents], retriever.details


def structured_messages(system, payload, *, examples=False):
    """Actual few-shot examples teach evidence boundaries, not Golden answers."""
    messages = [SystemMessage(content=system)]
    if examples:
        example = {'goal': '제출 자료의 기한과 준비 순서를 알려줘.', 'evidence': {'facts': [
            {'fact_id': 'F1', 'source_quotes': [{'quote': '신청서는 2030년 4월 2일 15시까지 방문 제출한다.'}]},
            {'fact_id': 'F2', 'source_quotes': [{'quote': '선정된 업체는 계약 체결 전에 보안계획서를 제출한다.'}]}]}}
        answer = {'claims': [
            {'claim_id': 'example-1', 'text': '신청서를 먼저 준비하여 2030년 4월 2일 15시까지 방문 제출해야 합니다.',
             'fact_ids': ['F1'], 'speech_act': 'ASSERTION'},
            {'claim_id': 'example-2', 'text': '선정된 경우 보안계획서는 계약 체결 전에 제출해야 합니다. 계약일이 없어 날짜는 확정할 수 없습니다.',
             'fact_ids': ['F2'], 'speech_act': 'ASSERTION'}]}
        messages.extend([HumanMessage(content=json.dumps(example, ensure_ascii=False)),
                         AIMessage(content=json.dumps(answer, ensure_ascii=False))])
        messages.extend([
            HumanMessage(content=json.dumps({'current_date':'2031-05-01','goal':'일정과 참여 조건 확인',
                'evidence':{'facts':[{'fact_id':'F1','source_quotes':[{'quote':'설명회 예정일: 2031년 4월 1일. A 또는 B 자격을 가진 사람만 참석할 수 있다.'}]}]}},ensure_ascii=False)),
            AIMessage(content=json.dumps({'claims':[{'claim_id':'example-past','text':'설명회 예정일은 지났습니다. 실제 개최·참석 여부는 별도로 확인해야 합니다. 참석자는 A 또는 B 자격을 갖춰야 하며 A만으로 제한되지 않습니다.',
                'fact_ids':['F1'],'speech_act':'ASSERTION'}]},ensure_ascii=False))])
    # Use a variable for the real payload; source braces are never interpreted as templates.
    messages.append(('human', '{payload}'))
    return ChatPromptTemplate.from_messages(messages).invoke({'payload': payload})


def invoke_structured(client, *, model, prompt, schema, output_limit, timeout):
    def send(prompt_value):
        roles = {'system': 'system', 'human': 'user', 'ai': 'assistant'}
        return client.with_options(max_retries=0, timeout=timeout).chat.completions.parse(
            model=model,
            messages=[{'role': roles[m.type], 'content': m.content} for m in prompt_value.to_messages()],
            response_format=schema, max_completion_tokens=output_limit)
    return RunnableLambda(send, name='copilot.budgeted_structured_model').invoke(prompt)
