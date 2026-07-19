import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Search } from "lucide-react";
import { Link, useParams } from "react-router";

import {
  correctMemory,
  listMemory,
  revokeMemory,
  searchMemory,
  type MemoryRecord,
} from "../api/client";
import { queryKeys } from "../app/queryKeys";

export function MemoryPage() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const records = useQuery({
    queryKey: queryKeys.memory(projectId),
    queryFn: () => listMemory(projectId),
  });
  const [kind, setKind] = useState<MemoryRecord["kind"] | "all">("all");
  const [status, setStatus] = useState<MemoryRecord["status"] | "all">(
    "active",
  );
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<
    Array<{ path: string; location: string; quote: string; sha256: string }>
  >([]);
  const [editing, setEditing] = useState<MemoryRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const filtered = useMemo(
    () =>
      records.data?.filter(
        (record) =>
          (kind === "all" || record.kind === kind) &&
          (status === "all" || record.status === status),
      ) ?? [],
    [kind, records.data, status],
  );
  const correct = useMutation({
    mutationFn: (record: MemoryRecord) => correctMemory(projectId, record),
    onSuccess: () => {
      setEditing(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.memory(projectId),
      });
    },
    onError: (cause) => setError(cause.message),
  });
  const revoke = useMutation({
    mutationFn: (record: MemoryRecord) => revokeMemory(projectId, record),
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: queryKeys.memory(projectId),
      }),
    onError: (cause) => setError(cause.message),
  });
  async function search() {
    if (!query.trim()) return;
    try {
      setHits(await searchMemory(projectId, query));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "搜索失败");
    }
  }
  const chapterLink = (source: string) => {
    const match = /^canon\/chapters\/(.+)\.md$/.exec(source);
    return match ? `/projects/${projectId}/chapters/${match[1]}` : null;
  };
  const kindLabels = {
    fact: "事实",
    event: "事件",
    relationship: "关系",
    foreshadowing: "伏笔",
  } as const;
  return (
    <div className="memory-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">记忆中心</span>
          <h1>可追溯的长期记忆</h1>
          <p>每条正式记忆都必须指回已经确认的章节原文。</p>
        </div>
        <div className="memory-summary">
          <strong>
            {records.data?.filter((item) => item.status === "active").length ??
              0}
          </strong>
          <span>条生效</span>
        </div>
      </header>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      <div className="memory-filters">
        <div className="segmented">
          <button
            className={kind === "all" ? "is-active" : ""}
            type="button"
            onClick={() => setKind("all")}
          >
            全部
          </button>
          {Object.entries(kindLabels).map(([value, label]) => (
            <button
              className={kind === value ? "is-active" : ""}
              type="button"
              key={value}
              onClick={() => setKind(value as MemoryRecord["kind"])}
            >
              {label}
            </button>
          ))}
        </div>
        <select
          aria-label="记忆状态"
          value={status}
          onChange={(event) => setStatus(event.target.value as typeof status)}
        >
          <option value="active">生效</option>
          <option value="resolved">已解决</option>
          <option value="superseded">已撤销</option>
          <option value="all">全部状态</option>
        </select>
        <div className="search-field">
          <Search size={15} />
          <input
            aria-label="搜索记忆"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && void search()}
            placeholder="搜索正文与记忆"
          />
        </div>
      </div>
      <div className="memory-layout">
        <section className="memory-table">
          {filtered.map((record) => (
            <article key={`${record.kind}-${record.id}`}>
              <div className="memory-kind">{kindLabels[record.kind]}</div>
              <div>
                <strong>{record.content ?? record.id}</strong>
                <p>{record.quote}</p>
                <small>
                  {record.id} · {record.status}
                </small>
              </div>
              <div className="memory-source">
                {chapterLink(record.source) ? (
                  <Link to={chapterLink(record.source)!}>
                    {record.source}
                    <ExternalLink size={12} />
                  </Link>
                ) : (
                  <span>{record.source}</span>
                )}
                <small>{record.location}</small>
              </div>
              <div className="row-actions">
                <button
                  className="button button-secondary"
                  type="button"
                  onClick={() => setEditing(record)}
                >
                  修正
                </button>
                {record.status === "active" && (
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => revoke.mutate(record)}
                  >
                    撤销
                  </button>
                )}
              </div>
            </article>
          ))}
          {!filtered.length && (
            <div className="editor-empty">当前筛选条件下没有记忆。</div>
          )}
        </section>
        <aside className="search-results">
          <h2>搜索结果</h2>
          {hits.map((hit) => (
            <article key={`${hit.path}-${hit.location}`}>
              <strong>{hit.path}</strong>
              <small>{hit.location}</small>
              <p>{hit.quote}</p>
            </article>
          ))}
          {!hits.length && (
            <p className="muted">输入两个以上字符搜索正式正文和记忆。</p>
          )}
        </aside>
      </div>
      {editing && (
        <div className="dialog-backdrop">
          <div className="dialog">
            <div className="dialog-heading">
              <div>
                <span className="eyebrow">修正记忆</span>
                <h2>{editing.id}</h2>
              </div>
            </div>
            <label>
              来源
              <input
                value={editing.source}
                onChange={(event) =>
                  setEditing({ ...editing, source: event.target.value })
                }
              />
            </label>
            <label>
              位置
              <input
                value={editing.location}
                onChange={(event) =>
                  setEditing({ ...editing, location: event.target.value })
                }
              />
            </label>
            <label>
              原文引用
              <textarea
                value={editing.quote}
                onChange={(event) =>
                  setEditing({ ...editing, quote: event.target.value })
                }
              />
            </label>
            <div className="dialog-actions">
              <button
                className="button button-secondary"
                type="button"
                onClick={() => setEditing(null)}
              >
                取消
              </button>
              <button
                className="button button-primary"
                type="button"
                onClick={() => correct.mutate(editing)}
              >
                保存修正
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
