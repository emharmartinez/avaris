import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const SAFE_HREF = /^(https?:\/\/|#)/i;

// Props are picked explicitly: react-markdown also passes `node`, which must not reach the DOM
const components: Components = {
  h1: ({ children }) => <h1 className="mt-6 mb-3 text-2xl font-semibold tracking-tight first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="mt-6 mb-2 text-xl font-semibold tracking-tight">{children}</h2>,
  h3: ({ children }) => <h3 className="mt-4 mb-2 text-lg font-semibold">{children}</h3>,
  h4: ({ children }) => <h4 className="mt-4 mb-2 font-semibold">{children}</h4>,
  p: ({ children }) => <p className="my-3 leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="my-3 list-disc space-y-1 pl-6">{children}</ul>,
  ol: ({ children }) => <ol className="my-3 list-decimal space-y-1 pl-6">{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 pl-4 text-muted-foreground">{children}</blockquote>
  ),
  hr: () => <hr className="my-6 border-border" />,
  pre: ({ children }) => (
    <pre className="my-3 overflow-x-auto rounded-md bg-muted p-3 text-xs [&>code]:bg-transparent [&>code]:p-0">{children}</pre>
  ),
  code: ({ children, className }) => (
    <code className={className ?? "rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]"}>{children}</code>
  ),
  table: ({ children }) => (
    <div className="my-4 overflow-x-auto">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="border-b">{children}</thead>,
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => <tr className="border-b last:border-0">{children}</tr>,
  th: ({ children, style }) => (
    <th style={style} className="px-2 py-1.5 text-left font-medium whitespace-nowrap">{children}</th>
  ),
  td: ({ children, style }) => (
    <td style={style} className="px-2 py-1.5 tabular-nums whitespace-nowrap">{children}</td>
  ),
  // Only web and in-page links; anything else (javascript:, data:, relative) renders as text
  a: ({ href, children }) =>
    href && SAFE_HREF.test(href)
      ? <a href={href} rel="noreferrer" className="underline underline-offset-4">{children}</a>
      : <span>{children}</span>,
  // Charts are rendered separately; images inside a report show their alt text
  img: ({ alt }) => <span className="italic text-muted-foreground">{alt}</span>,
};

// Report markdown: GFM, and raw HTML stays literal text (no rehype-raw)
export function Markdown({ children }: { children: string }) {
  return (
    <div className="text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} skipHtml={false}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
