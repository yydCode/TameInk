import { ChangeSet, simplifyChanges } from "prosemirror-changeset";
import type { Node } from "prosemirror-model";
import { schema } from "prosemirror-schema-basic";
import { StepMap } from "prosemirror-transform";

export interface ReviewChange {
  id: string;
  fromA: number;
  toA: number;
  fromB: number;
  toB: number;
  before: string;
  after: string;
}

function textDocument(text: string): Node {
  return schema.node("doc", null, [
    schema.node("paragraph", null, text ? [schema.text(text)] : undefined),
  ]);
}

function offset(position: number, length: number): number {
  return Math.max(0, Math.min(length, position - 1));
}

export function reviewChanges(before: string, after: string): ReviewChange[] {
  if (before === after) return [];
  const oldDoc = textDocument(before);
  const newDoc = textDocument(after);
  const map = new StepMap([0, oldDoc.content.size, newDoc.content.size]);
  const changes = simplifyChanges(
    ChangeSet.create(oldDoc).addSteps(newDoc, [map], null).changes,
    newDoc,
  );
  return changes.map((change, index) => {
    const fromA = offset(change.fromA, before.length);
    const toA = offset(change.toA, before.length);
    const fromB = offset(change.fromB, after.length);
    const toB = offset(change.toB, after.length);
    return {
      id: `change-${index + 1}`,
      fromA,
      toA,
      fromB,
      toB,
      before: before.slice(fromA, toA),
      after: after.slice(fromB, toB),
    };
  });
}

export function applyReview(
  before: string,
  after: string,
  acceptedIds: ReadonlySet<string>,
): string {
  const changes = reviewChanges(before, after);
  let result = "";
  let cursor = 0;
  for (const change of changes) {
    result += before.slice(cursor, change.fromA);
    result += acceptedIds.has(change.id) ? change.after : change.before;
    cursor = change.toA;
  }
  return result + before.slice(cursor);
}

export function appendEditorSteps(doc: Node, maps: readonly StepMap[]): ChangeSet {
  return ChangeSet.create(doc).addSteps(doc, maps, maps.map(() => null));
}
