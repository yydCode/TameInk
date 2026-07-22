import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Braces, Play, RotateCcw } from "lucide-react";
import { useNavigate, useParams } from "react-router";

import { runCreativeSkill, type P0Skill } from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { skillLabels } from "./creativeUi";

const executableSkills: P0Skill[] = [
  "webnovel-research-genre",
  "webnovel-design-reader-contract",
  "webnovel-design-story-engine",
  "webnovel-plan-rolling-story",
  "webnovel-plan-chapter",
  "webnovel-draft",
  "webnovel-audit",
  "webnovel-opening-audit",
  "webnovel-poison-check",
  "webnovel-curate-memory",
  "webnovel-plan-ending",
];

export function CreativePage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [skill, setSkill] = useState<P0Skill>("webnovel-plan-chapter");
  const [instruction, setInstruction] = useState("");
  const [parameters, setParameters] = useState("{}");
  const run = useMutation({
    mutationFn: () => {
      let payload: Record<string, unknown>;
      try {
        const parsed: unknown = JSON.parse(parameters);
        if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error();
        payload = parsed as Record<string, unknown>;
      } catch {
        throw new Error("结构化参数必须是 JSON 对象。");
      }
      if (instruction.trim()) payload.instruction = instruction.trim();
      return runCreativeSkill(projectId, skill, payload);
    },
    onSuccess: () => {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.creativeNext(projectId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks(projectId) }),
      ]);
      navigate(`/projects/${projectId}/workspace`);
    },
  });

  return (
    <section className="creative-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">创作 / 明确执行</span>
          <h1>发起一项受控创作任务</h1>
          <p>只填写这一轮需要 AI 执行的范围。任务完成后必须由作者决定是否写入正式故事。</p>
        </div>
      </header>
      <form className="creative-task-form" onSubmit={(event) => { event.preventDefault(); run.mutate(); }}>
        <label>
          执行 Skill
          <select value={skill} onChange={(event) => setSkill(event.target.value as P0Skill)}>
            {executableSkills.map((value) => <option value={value} key={value}>{skillLabels[value]}</option>)}
          </select>
        </label>
        <label>
          作者指令
          <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="例如：基于已确认的故事卡，聚焦主角这次选择造成的不可逆代价。" />
        </label>
        <label>
          <span className="label-with-icon"><Braces size={13} />结构化参数</span>
          <textarea className="json-input" value={parameters} onChange={(event) => setParameters(event.target.value)} spellCheck={false} aria-describedby="parameter-help" />
          <small id="parameter-help">需要指定故事卡、章节或审查范围时，在此传入已确认记录的 ID；不确定字段时留空对象。</small>
        </label>
        {run.error ? <p className="inline-error">{run.error.message}</p> : null}
        <div className="creative-task-actions">
          <button className="button button-secondary" type="button" onClick={() => navigate(`/projects/${projectId}/workspace`)}><RotateCcw size={15} />返回工作台</button>
          <button className="button button-primary" type="submit" disabled={run.isPending}><Play size={15} />提交 AI 执行</button>
        </div>
      </form>
    </section>
  );
}
