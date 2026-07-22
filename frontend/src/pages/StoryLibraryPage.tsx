import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookMarked, FileSearch, ScrollText } from "lucide-react";
import { useParams } from "react-router";

import {
  getCreativeArtifactResult,
  getDocument,
  getProjectSnapshot,
  listCreativeArtifacts,
} from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { artifactLabels, artifactStatusLabel, artifactSummary } from "./creativeUi";

type Selection = { type: "formal"; path: string } | { type: "artifact"; id: string } | null;

export function StoryLibraryPage() {
  const { projectId = "" } = useParams();
  const [selection, setSelection] = useState<Selection>(null);
  const snapshot = useQuery({ queryKey: queryKeys.snapshot(projectId), queryFn: () => getProjectSnapshot(projectId) });
  const artifacts = useQuery({ queryKey: queryKeys.creativeArtifacts(projectId), queryFn: () => listCreativeArtifacts(projectId) });
  const formalPaths = useMemo(() => new Set(snapshot.data?.documents.map((document) => document.path) ?? []), [snapshot.data?.documents]);
  const selectedFormalPath = selection?.type === "formal" ? selection.path : "";
  const selectedArtifact = selection?.type === "artifact" ? artifacts.data?.find((artifact) => artifact.id === selection.id) : undefined;
  const formalDocument = useQuery({
    queryKey: queryKeys.document(projectId, selectedFormalPath),
    queryFn: () => getDocument(projectId, selectedFormalPath),
    enabled: Boolean(selectedFormalPath),
  });
  const artifactResult = useQuery({
    queryKey: ["creative-artifact-result", projectId, selectedArtifact?.id],
    queryFn: () => getCreativeArtifactResult(projectId, selectedArtifact!),
    enabled: Boolean(selectedArtifact),
  });
  const candidates = artifacts.data?.filter((artifact) => artifact.status !== "accepted" && artifact.status !== "rejected") ?? [];

  return (
    <section className="story-library-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">故事库 / 分层事实</span>
          <h1>正式故事与待确认材料</h1>
          <p>只有作者确认的文件属于故事事实；候选和假设始终单独保存。</p>
        </div>
      </header>
      <div className="story-library-layout">
        <aside className="story-library-index">
          <div className="library-index-heading"><BookMarked size={15} /><strong>正式故事</strong></div>
          {snapshot.data?.documents.length ? snapshot.data.documents.map((document) => (
            <button type="button" key={document.path} className={selection?.type === "formal" && selection.path === document.path ? "is-selected" : ""} onClick={() => setSelection({ type: "formal", path: document.path })}>
              <span>{document.title}</span><small>{document.word_count.toLocaleString("zh-CN")} 字</small>
            </button>
          )) : <p className="muted">尚无作者确认的故事文件。</p>}
          {artifacts.data?.filter((artifact) => artifact.status === "accepted" && artifact.formal_path && !formalPaths.has(artifact.formal_path)).map((artifact) => (
            <button type="button" key={artifact.id} className={selection?.type === "formal" && selection.path === artifact.formal_path ? "is-selected" : ""} onClick={() => artifact.formal_path && setSelection({ type: "formal", path: artifact.formal_path })}>
              <span>{artifactLabels[artifact.kind]}</span><small>已确认</small>
            </button>
          ))}
          <div className="library-index-heading"><FileSearch size={15} /><strong>待确认</strong></div>
          {candidates.length ? candidates.map((artifact) => (
            <button type="button" key={artifact.id} className={`library-candidate ${selection?.type === "artifact" && selection.id === artifact.id ? "is-selected" : ""} library-candidate--${artifact.source_layer}`} onClick={() => setSelection({ type: "artifact", id: artifact.id })}>
              <span>{artifactLabels[artifact.kind]}</span><small>{artifact.source_layer === "hypothesis" ? "假设" : artifactStatusLabel(artifact.status)}</small>
            </button>
          )) : <p className="muted">没有待确认材料。</p>}
        </aside>
        <section className="story-library-reader">
          {selection?.type === "formal" ? (
            <>
              <div className="section-title"><h2>正式文件</h2><span>{selection.path}</span></div>
              {formalDocument.isLoading ? <p className="muted">正在读取正式文件。</p> : null}
              {formalDocument.error ? <p className="inline-error">{formalDocument.error.message}</p> : null}
              {formalDocument.data ? <pre className="formal-document">{formalDocument.data.content}</pre> : null}
            </>
          ) : selectedArtifact ? (
            <>
              <div className="section-title"><h2>{artifactLabels[selectedArtifact.kind]}</h2><span className={`artifact-state artifact-state--${selectedArtifact.source_layer}`}>{selectedArtifact.source_layer === "hypothesis" ? "假设，不是故事事实" : artifactStatusLabel(selectedArtifact.status)}</span></div>
              <p className="artifact-summary">{artifactSummary(selectedArtifact, artifactResult.data)}</p>
              {artifactResult.data?.candidate?.payload ? <pre className="artifact-payload">{JSON.stringify(artifactResult.data.candidate.payload, null, 2)}</pre> : null}
            </>
          ) : (
            <div className="artifact-placeholder"><ScrollText size={23} /><p>从左侧选择一份正式文件或候选材料。</p></div>
          )}
        </section>
      </div>
    </section>
  );
}
