import { CirclePlus } from "lucide-react";

export function EmptyPage({ section = "项目概览" }: { section?: string }) {
  return (
    <section className="empty-state">
      <span className="manuscript-rule" />
      <h1>{section}需要一个作品</h1>
      <p>先选择已有作品，或建立一部新作品。</p>
      <button
        className="button button-primary"
        type="button"
        onClick={() => window.dispatchEvent(new Event("tame-ink:create"))}
      >
        <CirclePlus size={16} />
        创建第一部作品
      </button>
    </section>
  );
}
