import { type FormEvent, useState } from "react";
import { Plus, X } from "lucide-react";

const initialSetting = "# 故事设定\n\n从核心冲突、主角目标和世界规则开始。";

export interface CreateProjectInput {
  project_id: string;
  title: string;
  genre: string;
  target_words: number;
  constraints: string;
  setting_draft: string;
}

export function CreateProjectDialog({
  onClose,
  onCreate,
  busy,
}: {
  onClose: () => void;
  onCreate: (input: CreateProjectInput) => void;
  busy: boolean;
}) {
  const [form, setForm] = useState<CreateProjectInput>({
    project_id: "my-novel",
    title: "",
    genre: "",
    target_words: 2_000_000,
    constraints: "",
    setting_draft: initialSetting,
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    onCreate(form);
  }
  return (
    <div className="dialog-backdrop">
      <form className="dialog" onSubmit={submit}>
        <div className="dialog-heading">
          <div>
            <span className="eyebrow">新建作品</span>
            <h2>建立你的故事</h2>
          </div>
          <button
            className="icon-button"
            type="button"
            onClick={onClose}
            aria-label="关闭"
          >
            <X size={18} />
          </button>
        </div>
        <label htmlFor="project-id">项目 ID</label>
        <input
          id="project-id"
          value={form.project_id}
          onChange={(event) =>
            setForm({ ...form, project_id: event.target.value })
          }
          required
          pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
        />
        <div className="form-grid">
          <label>
            书名
            <input
              value={form.title}
              onChange={(event) =>
                setForm({ ...form, title: event.target.value })
              }
              required
            />
          </label>
          <label>
            题材
            <input
              value={form.genre}
              onChange={(event) =>
                setForm({ ...form, genre: event.target.value })
              }
              required
            />
          </label>
        </div>
        <label>
          目标字数
          <input
            type="number"
            min="1"
            value={form.target_words}
            onChange={(event) =>
              setForm({ ...form, target_words: Number(event.target.value) })
            }
            required
          />
        </label>
        <label>
          创作约束
          <textarea
            value={form.constraints}
            onChange={(event) =>
              setForm({ ...form, constraints: event.target.value })
            }
            required
          />
        </label>
        <label>
          初始设定
          <textarea
            value={form.setting_draft}
            onChange={(event) =>
              setForm({ ...form, setting_draft: event.target.value })
            }
            required
          />
        </label>
        <div className="dialog-actions">
          <button
            className="button button-secondary"
            type="button"
            onClick={onClose}
          >
            取消
          </button>
          <button
            className="button button-primary"
            type="submit"
            disabled={busy}
          >
            <Plus size={15} />
            创建并进入工作台
          </button>
        </div>
      </form>
    </div>
  );
}
