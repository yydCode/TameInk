import { ChangeSet } from "prosemirror-changeset";
import type { Node } from "prosemirror-model";
import type { StepMap } from "prosemirror-transform";

export type DiffKind = "added" | "removed" | "unchanged";
export interface DiffPart { kind: DiffKind; text: string }

export function appendEditorSteps(doc: Node, maps: readonly StepMap[]): ChangeSet {
  return ChangeSet.create(doc).addSteps(doc, maps, maps.map(() => null));
}

export function markdownDiff(before: string, after: string): DiffPart[] {
  if (before === after) return [{ kind: "unchanged", text: before }];
  return [
    ...(before ? [{ kind: "removed" as const, text: before }] : []),
    ...(after ? [{ kind: "added" as const, text: after }] : []),
  ];
}
