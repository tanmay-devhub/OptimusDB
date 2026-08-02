// SQL syntax highlighter — ports the mockup's hlSql tokenizer to JSX.
// Two-pass: first split by string/number/comment/param tokens, then
// scan the surviving plain runs for keywords and function names. Used
// by both the editor overlay and the read-only SqlText component.

import type { ReactNode } from "react";

const KW =
  /\b(select|from|where|and|or|not|join|inner|left|right|outer|on|group|by|order|limit|offset|as|with|distinct|having|union|all|insert|into|values|update|set|delete|case|when|then|else|end|interval|desc|asc|exists|in|is|null|like|between|refresh|materialized|view|concurrently)\b/gi;
const FN = /\b(count|sum|avg|min|max|now|date_trunc|coalesce|extract|percentile_cont)(?=\s*\()/gi;

type Tag = "k" | "f" | "s" | "n" | "c" | "v" | "p";
const COLORS: Record<Tag, string> = {
  k: "#5cc8ff", // keyword
  f: "#ffb224", // function
  s: "#3ecf8e", // string literal
  n: "#f78c6c", // number
  c: "#5b6474", // comment
  v: "#c792ea", // placeholder ($1)
  p: "#c7cedb", // plain identifier
};

interface Props {
  sql: string;
  highlight?: string | null;
}

export function SqlText({ sql, highlight = null }: Props) {
  if (!sql) return <span />;
  const tokens: [Tag, string][] = [];
  const re = /(--[^\n]*)|('(?:[^'\\]|\\.)*')|(\$\d+)|(\b\d+(?:\.\d+)?\b)/g;
  let last = 0;
  let m: RegExpExecArray | null;

  const pushPlain = (txt: string) => {
    const combined = new RegExp(KW.source + "|" + FN.source, "gi");
    let l = 0;
    let mm: RegExpExecArray | null;
    while ((mm = combined.exec(txt))) {
      if (mm.index > l) tokens.push(["p", txt.slice(l, mm.index)]);
      const looksLikeFn = /\(/.test(txt.slice(mm.index + mm[0].length, mm.index + mm[0].length + 1));
      const isFn = looksLikeFn && new RegExp("^(?:" + FN.source + ")$", "i").test(mm[0]);
      tokens.push([isFn ? "f" : "k", mm[0]]);
      l = mm.index + mm[0].length;
    }
    if (l < txt.length) tokens.push(["p", txt.slice(l)]);
  };

  while ((m = re.exec(sql))) {
    if (m.index > last) pushPlain(sql.slice(last, m.index));
    const tag: Tag = m[1] ? "c" : m[2] ? "s" : m[3] ? "v" : "n";
    tokens.push([tag, m[0]]);
    last = m.index + m[0].length;
  }
  if (last < sql.length) pushPlain(sql.slice(last));

  const out: ReactNode[] = [];
  tokens.forEach(([t, s], i) => {
    if (highlight && t === "p" && s.includes(highlight)) {
      const idx = s.indexOf(highlight);
      if (idx > 0) out.push(<span key={`${i}a`} style={{ color: COLORS.p }}>{s.slice(0, idx)}</span>);
      out.push(
        <span
          key={`${i}b`}
          style={{
            color: "#e6eaf2",
            background: "rgba(92,200,255,.22)",
            borderRadius: 3,
            outline: "1px solid rgba(92,200,255,.4)",
          }}
        >
          {highlight}
        </span>,
      );
      if (idx + highlight.length < s.length) {
        out.push(<span key={`${i}c`} style={{ color: COLORS.p }}>{s.slice(idx + highlight.length)}</span>);
      }
    } else {
      out.push(
        <span key={i} style={{ color: COLORS[t], fontStyle: t === "c" ? "italic" : "normal" }}>
          {s}
        </span>,
      );
    }
  });
  return <span>{out}</span>;
}
