"""诊断、建议与推荐 API 路由。

提供三个端点：
- POST /projects/{project_id}/diagnostics：运行诊断 Agent
- GET  /projects/{project_id}/suggestions：获取建议通道输出
- GET  /projects/{project_id}/chapters/{chapter_id}/recommendations：获取素材推荐

所有端点在 Agent 失败时返回空列表，不抛 5xx 错误。
"""

from fastapi import APIRouter, Request

from app.agents.diagnostics import DiagnosticResult, DiagnosticsAgent
from app.agents.material_recommender import MaterialRecommender, Recommendation
from app.agents.suggestions import Suggestion, SuggestionsChannel

router = APIRouter(prefix="/projects/{project_id}", tags=["diagnostics"])


@router.post("/diagnostics", response_model=list[DiagnosticResult])
def run_diagnostics(project_id: str, request: Request) -> list[DiagnosticResult]:
    """运行诊断 Agent，返回三类诊断结论列表。

    任何子诊断失败或数据缺失时返回空列表，不抛错。
    """
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
