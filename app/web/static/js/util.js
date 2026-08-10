export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

export function downloadFile(content, filename, type) {
  const blob = new Blob([content], { type });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

export function splitIds(raw) {
  return String(raw ?? "")
    .split(/[,;，；]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function mdInline(text) {
  return text
    .replace(/`([^`\n]+)`/g, (_, code) => `<code class="md-inline">${code}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      (_, label, url) => `<a href="${url}" target="_blank" rel="noopener">${label}</a>`);
}

/** 轻量 Markdown → HTML 渲染（先转义再排版，安全）。 */
export function renderMarkdown(text) {
  const lines = String(text ?? "").split("\n");
  const out = [];
  let list = null; // "ul" | "ol"
  let quote = false;
  let code = false;
  let codeBuf = [];
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const flushQuote = () => { if (quote) { out.push("</blockquote>"); quote = false; } };

  for (const raw of lines) {
    if (code) {
      if (/^```/.test(raw.trim())) {
        code = false;
        out.push(`<pre class="md-code"><code>${esc(codeBuf.join("\n"))}</code></pre>`);
      } else {
        codeBuf.push(raw);
      }
      continue;
    }
    if (/^```/.test(raw.trim())) {
      closeList(); flushQuote();
      code = true; codeBuf = [];
      continue;
    }
    const line = esc(raw);
    const t = line.trim();
    if (!t) { closeList(); flushQuote(); out.push(""); continue; }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) { closeList(); flushQuote(); out.push("<hr>"); continue; }
    const h = t.match(/^(#{1,6})\s+(.*)$/);
    if (h) { closeList(); flushQuote(); const lv = h[1].length; out.push(`<h${lv}>${mdInline(h[2])}</h${lv}>`); continue; }
    const bq = t.match(/^&gt;\s?(.*)$/);
    if (bq) { closeList(); if (!quote) { out.push("<blockquote>"); quote = true; } out.push(`<p>${mdInline(bq[1])}</p>`); continue; }
    const ul = t.match(/^[-*]\s+(.*)$/);
    if (ul) { flushQuote(); if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; } out.push(`<li>${mdInline(ul[1])}</li>`); continue; }
    const ol = t.match(/^\d+\.\s+(.*)$/);
    if (ol) { flushQuote(); if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; } out.push(`<li>${mdInline(ol[1])}</li>`); continue; }
    closeList(); flushQuote(); out.push(`<p>${mdInline(t)}</p>`);
  }
  if (code) out.push(`<pre class="md-code"><code>${esc(codeBuf.join("\n"))}</code></pre>`);
  closeList(); flushQuote();
  return out.join("\n");
}
