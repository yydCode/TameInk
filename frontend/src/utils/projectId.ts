/**
 * 生成项目 ID。
 *
 * 项目 ID 是内部标识符（只出现在 URL 里），作者在界面上只看到书名，
 * 从不直接接触 ID。因此这里不做中文转拼音（不可靠且无收益），只：
 *   - 保留书名中的 ASCII 字母数字作为可读前缀（英文书名友好）
 *   - 纯中文/空书名时回退到 "project" 前缀
 *   - 始终追加随机后缀保证唯一性，并满足后端 kebab-case 校验
 *
 * 示例：
 *   "My Novel"        -> "my-novel-a3b2"
 *   "重生之最强学霸"   -> "project-x7k9"
 *   ""                -> "project-x7k9"
 */

function asciiSlug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function randomId(length: number): string {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let result = "";
  for (let i = 0; i < length; i += 1) {
    result += chars[Math.floor(Math.random() * chars.length)];
  }
  return result;
}

export function generateProjectId(title: string): string {
  const slug = asciiSlug(title.trim()).slice(0, 20).replace(/-+$/, "");
  const prefix = slug || "project";
  return `${prefix}-${randomId(4)}`;
}
