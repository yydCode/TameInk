import { useEffect } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "@tiptap/markdown";
import { Bold, Italic, List, Redo2, Undo2 } from "lucide-react";

interface NovelEditorProps {
  markdown: string;
  onChange: (markdown: string) => void;
  readOnly?: boolean;
}

export function NovelEditor({ markdown, onChange, readOnly = false }: NovelEditorProps) {
  const editor = useEditor({
    extensions: [StarterKit, Markdown.configure({}),],
    content: markdown,
    contentType: "markdown",
    editable: !readOnly,
    immediatelyRender: false,
    onUpdate: ({ editor: current }) => onChange(current.getMarkdown()),
  });

  useEffect(() => {
    if (!editor || editor.getMarkdown() === markdown) return;
    editor.commands.setContent(markdown, { contentType: "markdown" });
  }, [editor, markdown]);

  useEffect(() => {
    editor?.setEditable(!readOnly);
  }, [editor, readOnly]);

  if (!editor) return <div className="editor-loading">正在加载编辑器...</div>;

  return (
    <div className="novel-editor">
      {!readOnly && (
        <div className="editor-toolbar" aria-label="编辑工具">
          <button type="button" className={editor.isActive("bold") ? "is-active" : ""} onClick={() => editor.chain().focus().toggleBold().run()} aria-label="加粗" title="加粗"><Bold size={16} /></button>
          <button type="button" className={editor.isActive("italic") ? "is-active" : ""} onClick={() => editor.chain().focus().toggleItalic().run()} aria-label="斜体" title="斜体"><Italic size={16} /></button>
          <button type="button" className={editor.isActive("bulletList") ? "is-active" : ""} onClick={() => editor.chain().focus().toggleBulletList().run()} aria-label="项目列表" title="项目列表"><List size={16} /></button>
          <span className="toolbar-divider" />
          <button type="button" onClick={() => editor.chain().focus().undo().run()} disabled={!editor.can().undo()} aria-label="撤销" title="撤销"><Undo2 size={16} /></button>
          <button type="button" onClick={() => editor.chain().focus().redo().run()} disabled={!editor.can().redo()} aria-label="重做" title="重做"><Redo2 size={16} /></button>
        </div>
      )}
      <EditorContent editor={editor} className="editor-content" />
    </div>
  );
}

