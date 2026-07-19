import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, LoaderCircle, Trash2, Upload } from "lucide-react";
import { useParams } from "react-router";

import {
  approveImport,
  confirmImport,
  uploadImport,
  type ImportPreview,
  type Task,
} from "../api/client";
import { queryKeys } from "../app/queryKeys";

export function ImportPage() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [sourceEnd, setSourceEnd] = useState<Record<string, number> | null>(
    null,
  );
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState<string | null>(null);
  const importId = file
    ? file.name
        .replace(/\.[^.]+$/, "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "") || "book-import"
    : "book-import";
  const upload = useMutation({
    mutationFn: () => uploadImport(projectId, importId, file!),
    onSuccess: (value) => {
      setPreview(value);
      setSourceEnd(value.chapters.at(-1)?.end ?? null);
    },
    onError: (cause) => setError(cause.message),
  });
  const confirm = useMutation({
    mutationFn: async () => {
      const chapters = preview!.chapters.map((chapter, index) => ({
        ...chapter,
        end: preview!.chapters[index + 1]?.start ?? sourceEnd!,
      }));
      return confirmImport(projectId, importId, { ...preview!, chapters });
    },
    onSuccess: (value) => setTask(value.task),
    onError: (cause) => setError(cause.message),
  });
  const approve = useMutation({
    mutationFn: () => approveImport(projectId, importId, task!.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.snapshot(projectId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tasks(projectId),
      });
    },
    onError: (cause) => setError(cause.message),
  });
  function edit(index: number, field: "number" | "title", value: string) {
    if (!preview) return;
    setPreview({
      ...preview,
      chapters: preview.chapters.map((chapter, current) =>
        current === index
          ? { ...chapter, [field]: field === "number" ? Number(value) : value }
          : chapter,
      ),
    });
  }
  return (
    <div className="import-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">作品导入</span>
          <h1>校对后再写入正式章节</h1>
          <p>原文件永久保留，边界确认和正式写入是两个独立步骤。</p>
        </div>
      </header>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      <label className="file-drop">
        <input
          type="file"
          accept=".txt,.md,text/plain,text/markdown"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setPreview(null);
            setTask(null);
          }}
        />
        <Upload size={20} />
        <span>{file ? file.name : "选择 TXT 或 Markdown 文件"}</span>
      </label>
      <button
        className="button button-primary"
        type="button"
        disabled={!file || upload.isPending}
        onClick={() => upload.mutate()}
      >
        {upload.isPending ? (
          <LoaderCircle className="spin" size={15} />
        ) : (
          <Upload size={15} />
        )}
        解析章节
      </button>
      {preview && (
        <section className="import-preview">
          <div className="section-title">
            <h2>边界预览</h2>
            <span>
              {preview.chapters.length} 章 · {preview.encoding}
            </span>
          </div>
          <div className="boundary-list">
            {preview.chapters.map((chapter, index) => (
              <div
                className="boundary-row"
                key={`${chapter.start.character}-${index}`}
              >
                <input
                  aria-label={`第 ${index + 1} 条章号`}
                  type="number"
                  min="1"
                  value={chapter.number}
                  onChange={(event) =>
                    edit(index, "number", event.target.value)
                  }
                />
                <input
                  aria-label={`第 ${index + 1} 条标题`}
                  value={chapter.title}
                  onChange={(event) => edit(index, "title", event.target.value)}
                />
                <span>第 {chapter.start.line} 行</span>
                <button
                  className="icon-button"
                  type="button"
                  aria-label={`移除 ${chapter.title}`}
                  onClick={() =>
                    setPreview({
                      ...preview,
                      chapters: preview.chapters.filter(
                        (_, current) => current !== index,
                      ),
                    })
                  }
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
          {!task ? (
            <button
              className="button button-secondary"
              type="button"
              onClick={() => confirm.mutate()}
              disabled={confirm.isPending || !preview.chapters.length}
            >
              <Check size={15} />
              确认章节边界
            </button>
          ) : (
            <div className="import-approval">
              <span>候选已写入任务 {task.id.slice(0, 8)}</span>
              <button
                className="button button-primary"
                type="button"
                onClick={() => approve.mutate()}
                disabled={approve.isPending}
              >
                <Check size={15} />
                批准并写入正式章节
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
