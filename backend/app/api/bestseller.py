"""爆款拆解 API 路由。

端点：
- POST /projects/{project_id}/bestseller/analyze：拆解爆款文本
- POST /projects/{project_id}/bestseller/template：从拆解结果生成模板
- GET  /projects/{project_id}/bestseller/templates：列出已保存模板
  （暂返回空列表，模板保存由前端 localStorage 处理）
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.agents.bestseller_analyzer import BestsellerAnalysis, BestsellerAnalyzer
from app.agents.pattern_template import PatternTemplate, PatternTemplateBuilder

router = APIRouter(prefix="/projects/{project_id}/bestseller", tags=["bestseller"])


class AnalyzeRequest(BaseModel):
    """爆款拆解请求。"""

    source_title: str = Field(description="来源书名")
    source_genre: str = Field(description="来源题材")
    chapters: list[str] = Field(description="章节文本列表")


class BuildTemplateRequest(BaseModel):
    """套路模板生成请求。"""

    analysis: BestsellerAnalysis = Field(description="爆款拆解结果")
    template_name: str = Field(description="模板名称")


@router.post("/analyze", response_model=BestsellerAnalysis)
def analyze_bestseller(
    project_id: str, req: AnalyzeRequest, request: Request
) -> BestsellerAnalysis:
    """拆解爆款文本，返回结构化分析结果。

    分析失败时返回空结果（0 章节），不抛错。
    """
    return BestsellerAnalyzer().analyze(req.source_title, req.source_genre, req.chapters)


@router.post("/template", response_model=PatternTemplate)
def build_template(
    project_id: str, req: BuildTemplateRequest, request: Request
) -> PatternTemplate:
    """从拆解结果生成可复用的套路模板。

    生成失败时返回零值模板，不抛错。
    """
    return PatternTemplateBuilder().build_from_analysis(req.analysis, req.template_name)


@router.get("/templates", response_model=list[PatternTemplate])
def list_templates(project_id: str, request: Request) -> list[PatternTemplate]:
    """列出已保存模板。

    模板保存由前端 localStorage 处理，后端暂不持久化，返回空列表。
    """
    return []
