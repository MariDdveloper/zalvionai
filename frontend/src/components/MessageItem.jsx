import { memo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Copy, Check, FileText, Image as ImageIcon, Loader2, Film } from "lucide-react";
import { API } from "../lib/api";

function CodeBlock({ inline, className, children }) {
  const [copied, setCopied] = useState(false);
  const match = /language-(\w+)/.exec(className || "");
  const code = String(children).replace(/\n$/, "");
  if (inline || !match) return <code className={className}>{children}</code>;
  const copy = () => { navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1500); };
  return (
    <div className="relative group my-3 rounded-xl overflow-hidden border border-[var(--border-subtle)]">
      <div className="flex items-center justify-between px-4 py-1.5 bg-[#F3F2EC] text-xs text-[var(--text-secondary)] font-mono">
        <span>{match[1]}</span>
        <button onClick={copy} className="flex items-center gap-1 hover:text-[var(--text-primary)] transition-colors">
          {copied ? <Check size={13} /> : <Copy size={13} />}{copied ? "Copied" : "Copy"}
        </button>
      </div>
      <SyntaxHighlighter language={match[1]} style={oneLight} customStyle={{ margin: 0, background: "#FBFAF6", fontSize: "0.85rem", padding: "1rem" }}>
        {code}
      </SyntaxHighlighter>
    </div>
  );
}

function MessageItem({ message, isStreaming }) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);

  if (isUser) {
    return (
      <div className="flex justify-end fade-up" data-testid="message-user">
        <div className="max-w-[80%]">
          {message.attachments?.length > 0 && (
            <div className="flex flex-wrap gap-2 justify-end mb-2">
              {message.attachments.map((a, i) => (
                <div key={i} className="flex items-center gap-1.5 text-xs bg-black/[0.04] border border-[var(--border-subtle)] rounded-lg px-2.5 py-1.5">
                  {a.kind === "image" ? <ImageIcon size={13} /> : <FileText size={13} />}{a.name || (a.kind === "image" ? "image" : "file")}
                </div>
              ))}
            </div>
          )}
          {message.content && (
            <div className="bg-black/[0.05] rounded-2xl px-5 py-3 text-[var(--text-primary)] whitespace-pre-wrap leading-relaxed">
              {message.content}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-4 fade-up group" data-testid="message-assistant">
      <div className="claus-orb flex-shrink-0 mt-1" style={{ width: 30, height: 30 }} />
      <div className="flex-1 min-w-0">
        {message.type === "image" && message.image_url ? (
          <div>
            <img src={message.image_url} alt="generated" className="rounded-2xl max-w-md w-full border border-[var(--border-subtle)] shadow-sm" />
            {message.content && <p className="text-sm text-[var(--text-secondary)] mt-2">{message.content}</p>}
          </div>
        ) : (
          <div className={`prose-claus max-w-none ${isStreaming ? "caret-blink" : ""}`}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ code: CodeBlock }}>
              {message.content || ""}
            </ReactMarkdown>
          </div>
        )}
        {!isStreaming && message.type !== "image" && message.content && (
          <button onClick={() => { navigator.clipboard.writeText(message.content); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
            className="opacity-0 group-hover:opacity-100 transition-opacity mt-2 flex items-center gap-1 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            {copied ? <Check size={13} /> : <Copy size={13} />}{copied ? "Copied" : "Copy"}
          </button>
        )}
      </div>
    </div>
  );
}

function VideoBlock({ message }) {
  if (message.status === "generating") {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-[var(--border-subtle)] bg-white px-5 py-6 max-w-md">
        <Loader2 size={20} className="animate-spin text-[var(--primary)]" />
        <div>
          <p className="font-medium flex items-center gap-1.5"><Film size={15} /> Generating video…</p>
          <p className="text-sm text-[var(--text-secondary)]">This can take a couple of minutes.</p>
        </div>
      </div>
    );
  }
  if (message.status === "error") {
    return <p className="text-[var(--error)]">{message.content || "Video generation failed."}</p>;
  }
  return (
    <video controls playsInline src={`${API}/videos/${message.video_id}`}
      className="rounded-2xl max-w-md w-full border border-[var(--border-subtle)] shadow-sm bg-black" />
  );
}

export default memo(MessageItem);
