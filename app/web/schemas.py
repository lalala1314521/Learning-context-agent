"""API 请求 / 响应模型。"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000000)
    output_format: str = Field("both", pattern="^(auto|both|mermaid|markdown)$")
    web_search_enabled: bool = False
    auto_link: bool = True
    selected_chapters: list[int] = []


class NodeCreate(BaseModel):
    graph_id: str
    label: str = Field(..., min_length=1, max_length=200)
    parent_id: Optional[str] = None
    note: str = ""
    node_type: str = "concept"
    related_nodes: list[str] = []
    order_index: int = 0


class NodeUpdate(BaseModel):
    label: Optional[str] = None
    note: Optional[str] = None
    node_type: Optional[str] = None
    related_nodes: Optional[list[str]] = None
    order_index: Optional[int] = None


class GraphLinkCreate(BaseModel):
    from_graph_id: str
    from_node_id: str
    to_graph_id: str
    to_node_id: str
    relation_type: str = "related"
    note: str = ""


class GraphUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class QuizCreate(BaseModel):
    graph_id: str
    node_id: str
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    question_type: str = "short_answer"
    difficulty: int = 1


class ReviewSubmit(BaseModel):
    rating: int = Field(..., ge=0, le=2)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    use_database: bool = True


class ConceptLinkStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|confirmed|rejected)$")


class ConceptMergeRequest(BaseModel):
    winner_id: str
    loser_id: str


class ApiResponse(BaseModel):
    ok: bool
    data: Any = None
    error: Optional[str] = None
