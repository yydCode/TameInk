import { type FormEvent, useState } from "react";
import { Plus, Sparkles, X } from "lucide-react";
import { generateProjectId } from "../../utils/projectId";
import { draftBrief } from "../../api/client";

export interface CreateProjectInput {
  project_id: string;
  title: string;
  platform: string;
  genre_scope: string;
  constraints: string;
  initial_intent: string;
  first_story_goal: string;
  material_boundaries: string;
}

const EMPTY: CreateProjectInput = {
  project_id: "",
  title: "",
  platform: "番茄小说",
  genre_scope: "",
  constraints: "",
  initial_intent: "",
  first_story_goal: "",
  material_boundaries: "",
};

/**
 * 两步式新建作品：
 *  step "idea"  — 作者用一句话描述想法，AI 拆解成结构化草稿
 *  step "review" — 展示草稿供作者编辑确认；作者也可跳过 AI 直接手填
 * 项目 ID 始终由书名自动生成，作者不感知。
 */
export function CreateProjectDialog({
  onClose,
  onCreate,
  busy,
}: {
  onClose: () => void;
  onCreate: (input: CreateProjectInput) => void;
  busy: boolean;
}) {
  const [step, setStep] = useState<"idea" | "review">("idea");
  const [idea, setIdea] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [form, setForm] = useState<CreateProjectInput>(EMPTY);

  async function runDraft(event: FormEvent) {
    event.preventDefault();
    if (!idea.trim()) return;
    setDrafting(true);
    setDraftError(null);
    try {
      const draft = await draftBrief(idea.trim());
      setForm({
        ...EMPTY,
        title: draft.title,
        genre_scope: draft.genre_scope,
        first_story_goal: draft.first_story_goal,
        initial_intent: draft.initial_intent,
      });
      setStep("review");
    } catch (error) {
      setDraftError(error instanceof Error ? error.message : "AI 起草失败，请重试或手动填写。");
    } finally {
      setDrafting(false);
    }
  }

  function skipToManual() {
    setForm(EMPTY);
    setStep("review");
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    onCreate({ ...form, project_id: generateProjectId(form.title) });
  }

  return (
    <div className="dialog-backdrop">
      {step === "idea" ? (
        <form className="dialog" onSubmit={runDraft}>
          <div className="dialog-heading">
            <div>
              <span className="eyebrow">新建作品</span>
              <h2>开始一部新作品</h2>
            </div>
            <button className="icon-button" type="button" onClick={onClose} aria-label="关闭">
              <X size={18} />
            </button>
          </div>
          <label>
            用一两句话描述你想写的故事
            <textarea
              value={idea}
              onChange={(event) => setIdea(event.target.value)}
              placeholder="例如：都市重生，主角回到高考前，靠超强记忆力逆袭，打脸曾经看不起他的人"
              rows={4}
              autoFocus
            />
          </label>
          {draftError ? <p className="inline-error">{draftError}</p> : null}
          <div className="dialog-actions">
            <button className="button button-secondary" type="button" onClick={skipToManual}>
              跳过，手动填写
            </button>
            <button
              className="button button-primary"
              type="submit"
              disabled={drafting || !idea.trim()}
            >
              <Sparkles size={15} />
              {drafting ? "AI 起草中…" : "AI 帮我搭框架"}
            </button>
          </div>
        </form>
      ) : (
        <form className="dialog" onSubmit={submit}>
          <div className="dialog-heading">
            <div>
              <span className="eyebrow">新建作品 · 审阅草稿</span>
              <h2>建立你的故事</h2>
            </div>
            <button className="icon-button" type="button" onClick={onClose} aria-label="关闭">
              <X size={18} />
            </button>
          </div>
          <div className="form-grid">
            <label>
              书名
              <input
                value={form.title}
                onChange={(event) => setForm({ ...form, title: event.target.value })}
                placeholder="给你的故事起个名字"
                required
                autoFocus
              />
            </label>
            <label>
              平台
              <select
                value={form.platform}
                onChange={(event) => setForm({ ...form, platform: event.target.value })}
              >
                <option value="番茄小说">番茄小说</option>
                <option value="起点中文网">起点中文网</option>
                <option value="晋江文学城">晋江文学城</option>
                <option value="其他">其他</option>
              </select>
            </label>
          </div>
          <label>
            题材视图
            <input
              value={form.genre_scope}
              onChange={(event) => setForm({ ...form, genre_scope: event.target.value })}
              placeholder="例如：都市重生、玄幻修仙、历史架空"
            />
          </label>
          <label>
            首个故事目标
            <textarea
              value={form.first_story_goal}
              onChange={(event) => setForm({ ...form, first_story_goal: event.target.value })}
              placeholder="主角先要完成什么，并让读者带着什么问题进入下一单元？"
              required
            />
          </label>
          <label>
            创作意图（可选）
            <textarea
              value={form.initial_intent}
              onChange={(event) => setForm({ ...form, initial_intent: event.target.value })}
              placeholder="你希望这个故事给读者什么样的阅读体验？"
            />
          </label>
          <div className="dialog-actions">
            <button className="button button-secondary" type="button" onClick={() => setStep("idea")}>
              返回
            </button>
            <button className="button button-primary" type="submit" disabled={busy}>
              <Plus size={15} />
              创建并进入工作台
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
