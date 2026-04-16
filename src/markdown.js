// Minimal markdown -> HTML converter for email rendering. Supports headings,
// bold/italic, inline code, fenced code blocks, links, lists, paragraphs,
// and blockquotes. NOT a full CommonMark implementation — just enough for
// the kind of output the agent typically produces.

const escapeHtml = (s) =>
  s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

// Inline transforms applied to already-escaped text. Order matters:
// code spans first (so their contents are not re-processed), then links,
// then bold, then italic.
const renderInline = (text) => {
  const codeSpans = [];
  let out = text.replace(/`([^`\n]+)`/g, (_, code) => {
    codeSpans.push(code);
    return `\u0000${codeSpans.length - 1}\u0000`;
  });

  out = out.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    (_, label, href) => `<a href="${href}">${label}</a>`,
  );

  out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  out = out.replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");

  out = out.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codeSpans[+i]}</code>`);
  return out;
};

export function markdownToHtml(md) {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;

  const flushList = (state) => {
    if (state.kind) {
      out.push(`</${state.kind}>`);
      state.kind = null;
      state.items = 0;
    }
  };

  const listState = { kind: null, items: 0 };

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    const fence = line.match(/^```(\w*)\s*$/);
    if (fence) {
      flushList(listState);
      const lang = fence[1] ? ` class="lang-${fence[1]}"` : "";
      const code = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) {
        code.push(lines[i]);
        i++;
      }
      i++;
      out.push(`<pre><code${lang}>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }

    // Headings (#, ##, ..., ######)
    const h = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (h) {
      flushList(listState);
      out.push(`<h${h[1].length}>${renderInline(escapeHtml(h[2]))}</h${h[1].length}>`);
      i++;
      continue;
    }

    // Horizontal rule
    if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) {
      flushList(listState);
      out.push("<hr>");
      i++;
      continue;
    }

    // Blockquote
    if (/^>\s?/.test(line)) {
      flushList(listState);
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      out.push(`<blockquote>${renderInline(escapeHtml(buf.join(" ")))}</blockquote>`);
      continue;
    }

    // Unordered list
    const ul = line.match(/^[-*+]\s+(.+)$/);
    if (ul) {
      if (listState.kind !== "ul") {
        flushList(listState);
        out.push("<ul>");
        listState.kind = "ul";
      }
      out.push(`<li>${renderInline(escapeHtml(ul[1]))}</li>`);
      listState.items++;
      i++;
      continue;
    }

    // Ordered list
    const ol = line.match(/^\d+\.\s+(.+)$/);
    if (ol) {
      if (listState.kind !== "ol") {
        flushList(listState);
        out.push("<ol>");
        listState.kind = "ol";
      }
      out.push(`<li>${renderInline(escapeHtml(ol[1]))}</li>`);
      listState.items++;
      i++;
      continue;
    }

    // Blank line ends paragraphs/lists
    if (line.trim() === "") {
      flushList(listState);
      i++;
      continue;
    }

    // Paragraph: gather consecutive non-blank lines
    flushList(listState);
    const para = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^```/.test(lines[i]) &&
      !/^#{1,6}\s/.test(lines[i]) &&
      !/^[-*+]\s/.test(lines[i]) &&
      !/^\d+\.\s/.test(lines[i]) &&
      !/^>\s?/.test(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    out.push(`<p>${renderInline(escapeHtml(para.join(" ")))}</p>`);
  }

  flushList(listState);
  return out.join("\n");
}

const STYLE = `
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; line-height: 1.5; color: #1a1a1a; max-width: 680px; margin: 24px auto; padding: 0 16px; }
  h1, h2, h3, h4 { line-height: 1.25; margin-top: 1.5em; }
  h1 { font-size: 1.8em; border-bottom: 1px solid #eee; padding-bottom: 0.3em; }
  h2 { font-size: 1.4em; border-bottom: 1px solid #eee; padding-bottom: 0.3em; }
  h3 { font-size: 1.15em; }
  code { background: #f4f4f4; padding: 0.15em 0.35em; border-radius: 3px; font-size: 0.9em; }
  pre { background: #f4f4f4; padding: 12px; border-radius: 6px; overflow-x: auto; }
  pre code { background: transparent; padding: 0; font-size: 0.85em; }
  blockquote { border-left: 4px solid #ddd; margin: 0; padding: 0 12px; color: #555; }
  a { color: #0366d6; }
  hr { border: none; border-top: 1px solid #eee; margin: 1.5em 0; }
  ul, ol { padding-left: 1.4em; }
  li { margin: 0.2em 0; }
`;

export function wrapEmailHtml(bodyHtml, title = "") {
  const safeTitle = escapeHtml(title);
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>${safeTitle}</title>
<style>${STYLE}</style></head>
<body>${bodyHtml}</body></html>`;
}
