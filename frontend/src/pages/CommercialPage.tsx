import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, LoaderCircle, Save, Sparkles } from "lucide-react";
import { useParams } from "react-router";

import {
  approveCommercialDraft,
  createCommercialObservation,
  generateCommercialProfile,
  getCommercialDraft,
  getCommercialMetrics,
  getCommercialProfile,
  listCommercialObservations,
  updateCommercialDraft,
  type CommercialObservationInput,
  type CommercialProfile,
} from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { CommercialChart } from "../components/charts/CommercialChart";
import { RunStatus } from "../features/runs/RunStatus";
import { useProjectWorkspace } from "../features/workspace/useProjectWorkspace";
import { useTaskStream } from "../hooks/useTaskStream";

const emptyProfile: CommercialProfile = {
  schema_version: 1,
  platform: "fanqie",
  custom_platform: null,
  monetization: "free_ad",
  target_reader: "",
  core_fantasy: "",
  differentiator: "",
  emotional_payoffs: [],
  opening_promise: "",
  first_thirty_chapter_promise: "",
  update_cadence: "每日两章",
  title_candidates: [],
  synopsis: "",
  comparable_titles: [],
  minimum_commercial_score: 75,
  targets: {
    click_through_rate: null,
    chapter_one_completion_rate: null,
    chapter_three_retention_rate: null,
    follow_rate: null,
    revenue_per_thousand_opens_yuan: null,
  },
};
const emptyObservation = (): CommercialObservationInput => ({
  observed_at: new Date().toISOString(),
  impressions: 1,
  opens: 1,
  chapter_one_completions: 0,
  chapter_three_completions: 0,
  follows: 0,
  read_minutes: 0,
  revenue_cents: 0,
});

export function CommercialPage() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const { project, tasks } = useProjectWorkspace(projectId);
  const formal = useQuery({
    queryKey: queryKeys.commercial(projectId),
    queryFn: () => getCommercialProfile(projectId),
  });
  const metrics = useQuery({
    queryKey: ["commercial-metrics", projectId],
    queryFn: () => getCommercialMetrics(projectId),
  });
  const observations = useQuery({
    queryKey: ["commercial-observations", projectId],
    queryFn: () => listCommercialObservations(projectId),
  });
  const task =
    tasks.data?.find(
      (item) =>
        item.purpose === "commercial" && item.status === "awaiting_approval",
    ) ??
    tasks.data?.find(
      (item) =>
        item.purpose === "commercial" &&
        ["pending", "running"].includes(item.status),
    );
  const draft = useQuery({
    queryKey: ["commercial-draft", projectId, task?.id],
    queryFn: () => getCommercialDraft(projectId, task!.id),
    enabled: task?.status === "awaiting_approval",
  });
  const [profile, setProfile] = useState<CommercialProfile>(emptyProfile);
  const [baseline, setBaseline] = useState<CommercialProfile>(emptyProfile);
  const [observation, setObservation] = useState(emptyObservation);
  const [error, setError] = useState<string | null>(null);
  const stream = useTaskStream(
    projectId,
    task && ["pending", "running"].includes(task.status) ? task.id : undefined,
  );
  useEffect(() => {
    const value = draft.data ?? formal.data ?? emptyProfile;
    setProfile(value);
    setBaseline(value);
  }, [draft.data, formal.data]);
  const dirty = useMemo(
    () => JSON.stringify(profile) !== JSON.stringify(baseline),
    [baseline, profile],
  );
  const generate = useMutation({
    mutationFn: () =>
      generateCommercialProfile(projectId, {
        platform: profile.platform,
        monetization: profile.monetization,
        target_reader: profile.target_reader || "目标读者",
        core_fantasy: profile.core_fantasy || "核心欲望",
        differentiator: profile.differentiator || "差异化机制",
        comparable_titles: profile.comparable_titles,
        instruction: "基于作品设定生成可验证、可跟踪指标的商业定位",
      }),
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tasks(projectId),
      }),
    onError: (cause) => setError(cause.message),
  });
  const save = useMutation({
    mutationFn: () => updateCommercialDraft(projectId, task!.id, profile),
    onSuccess: (value) => {
      setBaseline(value);
      setError(null);
    },
    onError: (cause) => setError(cause.message),
  });
  const approve = useMutation({
    mutationFn: () => approveCommercialDraft(projectId, task!.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.commercial(projectId),
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
  const record = useMutation({
    mutationFn: () => createCommercialObservation(projectId, observation),
    onSuccess: () => {
      setObservation(emptyObservation());
      void queryClient.invalidateQueries({
        queryKey: ["commercial-metrics", projectId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["commercial-observations", projectId],
      });
    },
    onError: (cause) => setError(cause.message),
  });
  function change<K extends keyof CommercialProfile>(
    key: K,
    value: CommercialProfile[K],
  ) {
    setProfile((current) => ({ ...current, [key]: value }));
  }

  if (!project.data)
    return <div className="loading-state">读取商业工作台...</div>;
  return (
    <div className="commercial-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">商业增长</span>
          <h1>番茄首测策略</h1>
          <p>
            {formal.data
              ? "正式定位已确认"
              : task
                ? "候选定位等待处理"
                : "用可观测指标定义作品承诺"}
          </p>
        </div>
        <div className="header-actions">
          <a
            className="icon-button"
            href={`/api/projects/${projectId}/exports/commercial.json`}
            aria-label="导出商业数据"
            title="导出商业数据"
          >
            <Download size={17} />
          </a>
          {task && (
            <RunStatus status={task.status} connection={stream.connection} />
          )}
        </div>
      </header>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      <section className="commercial-profile">
        <div className="commercial-form">
          <div className="segmented" aria-label="目标平台">
            {(["fanqie", "qidian", "jinjiang", "custom"] as const).map(
              (value) => (
                <button
                  type="button"
                  key={value}
                  className={profile.platform === value ? "is-active" : ""}
                  onClick={() => change("platform", value)}
                >
                  {
                    {
                      fanqie: "番茄",
                      qidian: "起点",
                      jinjiang: "晋江",
                      custom: "自定义",
                    }[value]
                  }
                </button>
              ),
            )}
          </div>
          {profile.platform === "custom" && (
            <label>
              平台名称
              <input
                value={profile.custom_platform ?? ""}
                onChange={(event) =>
                  change("custom_platform", event.target.value)
                }
              />
            </label>
          )}
          <label>
            目标读者
            <input
              value={profile.target_reader}
              onChange={(event) => change("target_reader", event.target.value)}
            />
          </label>
          <label>
            核心欲望
            <textarea
              value={profile.core_fantasy}
              onChange={(event) => change("core_fantasy", event.target.value)}
            />
          </label>
          <label>
            差异化机制
            <textarea
              value={profile.differentiator}
              onChange={(event) => change("differentiator", event.target.value)}
            />
          </label>
          <label>
            首章承诺
            <textarea
              value={profile.opening_promise}
              onChange={(event) =>
                change("opening_promise", event.target.value)
              }
            />
          </label>
          <label>
            前三十章承诺
            <textarea
              value={profile.first_thirty_chapter_promise}
              onChange={(event) =>
                change("first_thirty_chapter_promise", event.target.value)
              }
            />
          </label>
          <label>
            简介
            <textarea
              value={profile.synopsis}
              onChange={(event) => change("synopsis", event.target.value)}
            />
          </label>
          <label>
            最低商业分
            <input
              type="number"
              min="0"
              max="100"
              value={profile.minimum_commercial_score}
              onChange={(event) =>
                change("minimum_commercial_score", Number(event.target.value))
              }
            />
          </label>
          <div className="commercial-actions">
            <button
              className="button button-secondary"
              type="button"
              onClick={() => generate.mutate()}
              disabled={generate.isPending || Boolean(task)}
            >
              {generate.isPending ? (
                <LoaderCircle className="spin" size={15} />
              ) : (
                <Sparkles size={15} />
              )}
              AI 生成定位
            </button>
            {task?.status === "awaiting_approval" && (
              <>
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={!dirty || save.isPending}
                  onClick={() => save.mutate()}
                >
                  <Save size={15} />
                  保存候选
                </button>
                <button
                  className="button button-primary"
                  type="button"
                  disabled={
                    dirty ||
                    (profile.platform === "custom" && !profile.custom_platform)
                  }
                  onClick={() => approve.mutate()}
                >
                  <Check size={15} />
                  确认商业定位
                </button>
              </>
            )}
          </div>
        </div>
        <aside>
          <h2>当前状态</h2>
          <dl className="profile-ledger">
            <div>
              <dt>版本</dt>
              <dd>{formal.data ? "正式" : task ? "候选" : "未建立"}</dd>
            </div>
            <div>
              <dt>编辑状态</dt>
              <dd>{dirty ? "有未保存修改" : "已保存"}</dd>
            </div>
            <div>
              <dt>更新节奏</dt>
              <dd>{profile.update_cadence || "未设置"}</dd>
            </div>
          </dl>
        </aside>
      </section>
      {metrics.data && (
        <section className="metrics-section">
          <div className="section-title">
            <h2>真实数据漏斗</h2>
            <span>{observations.data?.length ?? 0} 次观测</span>
          </div>
          <CommercialChart
            metrics={metrics.data}
            observations={observations.data ?? []}
          />
          <div className="metric-strip">
            <span>
              点击率{" "}
              <strong>
                {(metrics.data.click_through_rate * 100).toFixed(1)}%
              </strong>
            </span>
            <span>
              首章完读{" "}
              <strong>
                {(metrics.data.chapter_one_completion_rate * 100).toFixed(1)}%
              </strong>
            </span>
            <span>
              三章留存{" "}
              <strong>
                {(metrics.data.chapter_three_retention_rate * 100).toFixed(1)}%
              </strong>
            </span>
            <span>
              千次打开收入{" "}
              <strong>
                ¥{metrics.data.revenue_per_thousand_opens_yuan.toFixed(2)}
              </strong>
            </span>
          </div>
          <div className="observation-form">
            {(
              [
                "impressions",
                "opens",
                "chapter_one_completions",
                "chapter_three_completions",
                "follows",
                "read_minutes",
                "revenue_cents",
              ] as const
            ).map((key) => (
              <label key={key}>
                {
                  {
                    impressions: "曝光",
                    opens: "打开",
                    chapter_one_completions: "首章完读",
                    chapter_three_completions: "三章完读",
                    follows: "追读",
                    read_minutes: "阅读分钟",
                    revenue_cents: "收入（分）",
                  }[key]
                }
                <input
                  type="number"
                  min="0"
                  value={observation[key]}
                  onChange={(event) =>
                    setObservation({
                      ...observation,
                      [key]: Number(event.target.value),
                    })
                  }
                />
              </label>
            ))}
            <button
              className="button button-primary"
              type="button"
              onClick={() => record.mutate()}
            >
              记录数据
            </button>
          </div>
          <div className="observation-list">
            {observations.data?.map((item) => (
              <div key={item.id}>
                <time>
                  {new Date(item.observed_at).toLocaleDateString("zh-CN")}
                </time>
                <span>{item.impressions} 曝光</span>
                <span>{item.opens} 打开</span>
                <strong>¥{(item.revenue_cents / 100).toFixed(2)}</strong>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
