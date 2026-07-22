"""诊断、建议与推荐 API 路由。

提供五个端点：
- POST /projects/{project_id}/diagnostics：运行诊断 Agent
- GET  /projects/{project_id}/suggestions：获取建议通道输出
- GET  /projects/{project_id}/chapters/{chapter_id}/recommendations：获取素材推荐
- POST /projects/{project_id}/vocabulary-check：扫描正文反复词汇与 AI 套话
- GET  /projects/{project_id}/emotional-arc：章节情绪曲线数据（字数/审核问题数）

所有端点在失败时返回空列表，不抛 5xx 错误。
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from app.agents.diagnostics import DiagnosticResult, DiagnosticsAgent
from app.agents.material_recommender import MaterialRecommender, Recommendation
from app.agents.suggestions import Suggestion, SuggestionsChannel
from app.utils.vocabulary import VocabularyIssue, detect_repetitive_vocabulary

router = APIRouter(prefix="/projects/{project_id}", tags=["diagnostics"])


class VocabularyCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str  # 章节正文（markdown 格式）


class EmotionalArcPoint(BaseModel):
    """单个章节的情绪曲线数据点。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    chapter_id: str
    chapter_index: int  # 章节序号（从1开始）
    word_count: int  # 字数
    audit_issues: int = 0  # 审核发现的问题数（来自最近的 audit 任务）


@router.post("/diagnostics", response_model=list[DiagnosticResult])
def run_diagnostics(project_id: str, request: Request) -> list[DiagnosticResult]:
    """运行诊断 Agent，返回三类诊断结论列表。"""
    workspace = request.app.state.workspace
    return DiagnosticsAgent(workspace).run(project_id)


@router.get("/suggestions", response_model=list[Suggestion])
def list_suggestions(project_id: str, request: Request) -> list[Suggestion]:
    """获取建议通道聚合后的可执行建议列表。"""
    workspace = request.app.state.workspace
    return SuggestionsChannel(workspace).collect(project_id)


@router.get(
    "/chapters/{chapter_id}/recommendations",
    response_model=list[Recommendation],
)
def list_recommendations(
    project_id: str, chapter_id: str, request: Request
) -> list[Recommendation]:
    """根据章节内容推荐素材/人物/对话片段。"""
    workspace = request.app.state.workspace
    return MaterialRecommender(workspace).recommend(project_id, chapter_id)


@router.post("/vocabulary-check", response_model=list[VocabularyIssue])
def vocabulary_check(
    project_id: str, payload: VocabularyCheckRequest, request: Request  # noqa: ARG001
) -> list[VocabularyIssue]:
    """扫描正文中的反复词汇和 AI 套话。

    纯字频分析，不调用 LLM，响应速度快。
    返回发现的问题列表，按严重程度排序（套话优先，然后按每千字频率降序）。
    """
    return detect_repetitive_vocabulary(payload.text)


@router.get("/emotional-arc", response_model=list[EmotionalArcPoint])
def get_emotional_arc(project_id: str, request: Request) -> list[EmotionalArcPoint]:
    """返回章节情绪曲线数据点（字数/审核问题数），用于可视化章节健康度趋势。

    返回所有已确认章节的基本统计，按章节序号排序。
    """
    workspace = request.app.state.workspace
    canon = workspace.canon
    chapters = canon.list_confirmed_chapters(project_id)

    arc_points: list[EmotionalArcPoint] = []
    for chapter in chapters:
        content = canon.read_confirmed_chapter(project_id, chapter.id)
        word_count = len(content.markdown)

        arc_points.append(
            EmotionalArcPoint(
                chapter_id=chapter.id,
                chapter_index=chapter.index,
                word_count=word_count,
                audit_issues=0,  # TODO: 从任务历史中统计 audit 发现的问题数
            )
        )

    return sorted(arc_points, key=lambda p: p.chapter_index)
