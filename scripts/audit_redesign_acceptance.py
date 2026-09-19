"""Offline acceptance probes; mocks all persistence/model calls.

Run: .venv/Scripts/python.exe -X utf8 scripts/audit_redesign_acceptance.py
Outputs observations, not a claim that product acceptance passed.
"""
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import config
config.DEEPSEEK_API_KEY = ''
config.TAVILY_API_KEY = ''
from app.services import review, jobs
from app.services.knowledge_contract import canonical_graph_view, normalize_node_payloads
from app.services.graph_generation import generate_graph_fields
from app.graph.agent import tools_node
from app.tools import react_tools
from langchain_core.messages import AIMessage
from app.web.routers import graphs
from app.web.schemas import GenerateRequest

observations = {}
with patch.object(review.repository, 'get_due_review', return_value=[{'id': 'review-1', 'concept_id': 'concept-1'}]), patch.object(review.repository, 'get_concept', return_value={'id': 'concept-1', 'canonical_label': '过拟合', 'summary': '过拟合会降低模型的泛化能力。'}), patch.object(review, 'submit_review') as persist:
    session = review.create_review_session(mode='feynman', count=1)
    item = session['items'][0]
    result = review.submit_session_item(session['id'], item['id'], {'text': '过拟合不会降低模型的泛化能力。', 'rating': 2})
    observations['feynman'] = {'review_id': item.get('review_id'), 'persistence_calls': persist.call_count, 'feedback_for_negated_answer': result['feedback']}

nodes = normalize_node_payloads([
    {'id': 'a', 'label': '原因', 'related_nodes': ['b'], 'relation_type': 'causes', 'evidence': '原文因果证据'},
    {'id': 'b', 'label': '结果', 'parent_id': 'a'},
])
observations['canonical_edges'] = canonical_graph_view({'id': 'fixture'}, nodes)['edges']

with patch.object(react_tools, 'generate_and_save_graph', return_value={'current_graph_id': ''}) as generate:
    tools_node({'messages': [AIMessage(content='', tool_calls=[{'name': 'tool_generate_graph', 'args': {'content': '材料正文'}, 'id': 'call-1'}])], 'learning_goal': '比较因果机制', 'generation_depth': 'deep'})
    observations['react_generation_arguments'] = {'args': generate.call_args.args, 'kwargs': generate.call_args.kwargs}

with patch('app.services.graph_generation.classify_content', return_value='S'), patch('app.services.graph_generation._generate_single_shot', return_value={}) as single:
    generate_graph_fields('材料正文', learning_goal='比较因果机制', generation_depth='deep')
    observations['source_passed_to_generator'] = single.call_args.args[0]

entered, release = threading.Event(), threading.Event()
class PausedGraph:
    def stream(self, *_args):
        entered.set()
        if not release.wait(5):
            raise RuntimeError('probe timed out')
        yield {'router': {}}

with patch.object(graphs, 'get_graph_runner', return_value=PausedGraph()):
    response = graphs.generate_graph_async(GenerateRequest(content='隔离取消测试'))
    job_id = response['data']['id']
    if not entered.wait(5):
        raise RuntimeError('probe did not enter runner')
    jobs.cancel_job(job_id)
    release.set()
    deadline = time.monotonic() + 5
    while jobs.get_job(job_id)['status'] == 'running' and time.monotonic() < deadline:
        time.sleep(.01)
    result = jobs.get_job(job_id)
    observations['cancel_real_generation_runner'] = {key: result[key] for key in ('status', 'stage', 'error', 'cancel_requested')}

print(json.dumps(observations, ensure_ascii=False, indent=2))
