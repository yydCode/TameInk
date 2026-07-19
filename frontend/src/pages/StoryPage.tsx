import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, LoaderCircle, Plus, Sparkles, XCircle } from "lucide-react";
import { useParams } from "react-router";

import {
  approveOutline,
  approveSetting,
  approveVolume,
  generateOutline,
  generateSetting,
  generateVolume,
  getDocument,
  getDraft,
  saveDraft,
  transitionTask,
  type Task,
} from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { NovelEditor } from "../components/editor/NovelEditor";
import { CharacterSystemPanel } from "./CharacterSystemPanel";
import { RunStatus } from "../features/runs/RunStatus";
import { useProjectWorkspace } from "../features/workspace/useProjectWorkspace";
import { useTaskStream } from "../hooks/useTaskStream";

type StoryTab = {
  id: string;
  label: string;
  purpose: Task["purpose"];
  subject: string;
  canonicalPath: string;
  draftPath: string;
  volumeId?: string;
  // 标记为本地数据 tab：不参与 AI 生成/审批流程，数据存 localStorage
  localOnly?: boolean;
};

export function StoryPage() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const { project, snapshot, tasks } = useProjectWorkspace(projectId);
  const [selected, setSelected] = useState("setting");
  const [nextVolume, setNextVolume] = useState("");
  const [localVolumes, setLocalVolumes] = useState<string[]>([]);
  const [instruction, setInstruction] = useState(
    "根据已确认内容生成可执行、可验证的候选稿。不要改变已经确认的事实。",
  );
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const tabs = useMemo<StoryTab[]>(
    () => [
      {
        id: "setting",
        label: "故事设定",
        purpose: "setting",
        subject: "setting",
        canonicalPath: "canon/world/setting.md",
        draftPath: "setting.md",
      },
      {
        id: "outline",
        label: "全书大纲",
        purpose: "book_outline",
        subject: "book",
        canonicalPath: "canon/outline.md",
        draftPath: "book-outline.md",
      },
      ...[
        ...new Set([
          ...(snapshot.data?.volumes.map((volume) => volume.id) ?? []),
          ...(tasks.data
            ?.filter(
              (task) => task.purpose === "volume_outline" && task.volume_id,
            )
            .map((task) => task.volume_id!) ?? []),
          ...localVolumes,
        ]),
      ].map((volumeId) => {
        const volume = snapshot.data?.volumes.find(
          (item) => item.id === volumeId,
        );
        return {
          id: `volume-${volumeId}`,
          label: volume?.title ?? `分卷 ${volumeId}`,
          purpose: "volume_outline" as const,
          subject: volumeId,
          canonicalPath: volume?.path ?? `canon/volumes/${volumeId}.md`,
          draftPath: `volume-${volumeId}.md`,
          volumeId,
        };
      }),
      // 人物体系：本地数据 tab，不参与 AI 流程，数据存 localStorage
      {
        id: "characters",
        label: "人物体系",
        purpose: "setting",
        subject: "characters",
        canonicalPath: "",
        draftPath: "",
        localOnly: true,
      },
    ],
    [localVolumes, snapshot.data?.volumes, tasks.data],
  );
  const tab = tabs.find((item) => item.id === selected) ?? tabs[0];
  const task =
    tasks.data?.find(
      (item) =>
        item.purpose === tab.purpose &&
        item.subject_id === tab.subject &&
        !["completed", "cancelled"].includes(item.status),
    ) ??
    tasks.data?.find(
      (item) => item.purpose === tab.purpose && item.subject_id === tab.subject,
    );
  const formalExists =
    snapshot.data?.documents.some(
      (document) => document.path === tab.canonicalPath,
    ) ?? false;
  const formal = useQuery({
    queryKey: queryKeys.document(projectId, tab.canonicalPath),
    queryFn: () => getDocument(projectId, tab.canonicalPath),
    enabled: formalExists && task?.status !== "awaiting_approval",
  });
  const draft = useQuery({
    queryKey: ["draft", projectId, task?.id, tab.draftPath],
    queryFn: () => getDraft(projectId, task!.id, tab.draftPath),
    enabled: task?.status === "awaiting_approval",
  });
  const stream = useTaskStream(
    projectId,
    task && ["pending", "running"].includes(task.status) ? task.id : undefined,
  );
  const taskId = task?.id;
  const taskStatus = task?.status;
  const taskUpdatedAt = task?.updated_at;

  useEffect(() => {
    const next = draft.data?.content ?? formal.data?.content ?? "";
    setContent(next);
    setSavedContent(next);
  }, [draft.data?.content, formal.data?.content, tab.id]);

  useEffect(() => {
    if (!taskId || taskStatus !== "awaiting_approval") return;
    void queryClient.invalidateQueries({
      queryKey: ["draft", projectId, taskId, tab.draftPath],
    });
  }, [projectId, queryClient, tab.draftPath, taskId, taskStatus, taskUpdatedAt]);

  useEffect(() => {
    if (
      !task ||
      task.status !== "awaiting_approval" ||
      content === savedContent ||
      !draft.data
    )
      return;
    const timer = window.setTimeout(() => {
      saveDraft(projectId, task.id, tab.draftPath, content, draft.data.revision)
        .then(() => setSavedContent(content))
        .catch((cause) =>
          setError(cause instanceof Error ? cause.message : "草稿保存失败"),
        );
    }, 700);
    return () => window.clearTimeout(timer);
  }, [content, draft.data, projectId, savedContent, tab.draftPath, task]);

  const generate = useMutation({
    mutationFn: async () => {
      if (tab.purpose === "setting") {
        if (!task || task.status !== "awaiting_approval")
          throw new Error("已确认设定当前只读，请通过版本恢复后重新生成");
        return generateSetting(projectId, task.id, instruction);
      }
      if (tab.purpose === "book_outline")
        return generateOutline(projectId, instruction);
      return generateVolume(projectId, tab.volumeId!, instruction);
    },
    onSuccess: () => {
      setError(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tasks(projectId),
      });
    },
    onError: (cause) => setError(cause.message),
  });
  const approve = useMutation({
    mutationFn: () =>
      tab.purpose === "setting"
        ? approveSetting(projectId, task!.id)
        : tab.purpose === "book_outline"
          ? approveOutline(projectId, task!.id)
          : approveVolume(projectId, tab.volumeId!, task!.id),
    onSuccess: () => {
      setError(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.snapshot(projectId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.workflow(projectId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tasks(projectId),
      });
    },
    onError: (cause) => setError(cause.message),
  });
  async function cancel() {
    if (!task) return;
    await transitionTask(projectId, task.id, "cancel");
    void queryClient.invalidateQueries({
      queryKey: queryKeys.tasks(projectId),
    });
  }
  function addVolume() {
    const id = nextVolume.trim();
    if (!/^[a-zA-Z0-9-]+$/.test(id)) {
      setError("分卷 ID 只能包含字母、数字和短横线");
      return;
    }
    setLocalVolumes((current) =>
      current.includes(id) ? current : [...current, id],
    );
    setSelected(`volume-${id}`);
    setNextVolume("");
  }

  if (!project.data)
    return <div className="loading-state">读取故事工作区...</div>;
  return (
    <div className="story-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">故事设计</span>
          <h1>{project.data.title}</h1>
          <p>正式内容与待确认候选分开显示。</p>
        </div>
        {task && (
          <RunStatus status={task.status} connection={stream.connection} />
        )}
      </header>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      <div className="story-tabs" role="tablist">
        {tabs.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={item.id === tab.id}
            className={item.id === tab.id ? "is-active" : ""}
            type="button"
            onClick={() => setSelected(item.id)}
          >
            {item.label}
          </button>
        ))}
        <span className="volume-add">
          <input
            aria-label="新分卷 ID"
            value={nextVolume}
            onChange={(event) => setNextVolume(event.target.value)}
            placeholder="分卷 ID"
          />
          <button
            className="icon-button"
            type="button"
            onClick={addVolume}
            aria-label="添加分卷"
            title="添加分卷"
          >
            <Plus size={15} />
          </button>
        </span>
      </div>
      {tab.localOnly ? (
        <CharacterSystemPanel projectId={projectId} />
      ) : (
        <div className="document-workbench">
          <section className="document-main">
            <div className="document-toolbar">
              <div>
                <span className="eyebrow">
                  {task?.status === "awaiting_approval"
                    ? "候选稿"
                    : formalExists
                      ? "正式稿"
                      : "尚未生成"}
                </span>
                <h2>{tab.label}</h2>
              </div>
              <div>
                {task && ["pending", "running"].includes(task.status) && (
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => void cancel()}
                  >
                    <XCircle size={15} />
                    取消
                  </button>
                )}
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={
                    generate.isPending ||
                    task?.status === "pending" ||
                    task?.status === "running"
                  }
                  onClick={() => generate.mutate()}
                >
                  {generate.isPending || task?.status === "running" ? (
                    <LoaderCircle className="spin" size={15} />
                  ) : (
                    <Sparkles size={15} />
                  )}
                  AI 生成候选
                </button>
                {task?.status === "awaiting_approval" && (
                  <button
                    className="button button-primary"
                    type="button"
                    disabled={approve.isPending || content !== savedContent}
                    onClick={() => approve.mutate()}
                  >
                    <Check size={15} />
                    确认当前草稿
                  </button>
                )}
              </div>
            </div>
            {content ? (
              <NovelEditor
                markdown={content}
                onChange={setContent}
                readOnly={task?.status !== "awaiting_approval"}
              />
            ) : (
              <div className="editor-empty">输入指令并生成候选稿。</div>
            )}
          </section>
          <aside className="instruction-rail">
            <span className="eyebrow">Agent 指令</span>
            <textarea
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
            />
            <dl>
              <div>
                <dt>任务类型</dt>
                <dd>{tab.purpose}</dd>
              </div>
              <div>
                <dt>正式路径</dt>
                <dd>{tab.canonicalPath}</dd>
              </div>
              <div>
                <dt>保存状态</dt>
                <dd>{content === savedContent ? "已保存" : "待保存"}</dd>
              </div>
            </dl>
            {stream.error && <p className="inline-error">{stream.error}</p>}
          </aside>
        </div>
      )}
    </div>
  );
}
