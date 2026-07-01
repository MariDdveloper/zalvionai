import { useState } from "react";
import { Plus, Search, Trash2, Download, LogOut, PanelLeftClose, MessageSquare } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import LanguageMenu from "./LanguageMenu";

export default function Sidebar({ chats, activeId, onNew, onSelect, onDelete, onClose, lang, onLang, t, onDownload }) {
  const { user, logout } = useAuth();
  const [q, setQ] = useState("");
  const filtered = chats.filter((c) => (c.title || "").toLowerCase().includes(q.toLowerCase()));

  return (
    <div className="h-full flex flex-col bg-[var(--bg-sidebar)] border-r border-[var(--border-subtle)] w-[270px]">
      <div className="flex items-center justify-between px-4 py-4">
        <div className="flex items-center gap-2.5">
          <div className="claus-orb" style={{ width: 30, height: 30 }} />
          <span className="font-serif text-xl">Claus IA</span>
        </div>
        <button onClick={onClose} className="lg:hidden p-1.5 rounded-lg hover:bg-black/5"><PanelLeftClose size={18} /></button>
      </div>

      <div className="px-3">
        <button data-testid="new-chat-button" onClick={onNew}
          className="w-full flex items-center gap-2 bg-white border border-[var(--border-subtle)] rounded-xl px-3.5 py-2.5 font-medium text-[var(--text-primary)] hover:border-[var(--primary)] hover:text-[var(--primary)] transition-colors shadow-sm">
          <Plus size={18} strokeWidth={2} /> {t.newChat}
        </button>
      </div>

      <div className="px-3 mt-3">
        <div className="flex items-center gap-2 bg-black/[0.03] rounded-xl px-3 py-2">
          <Search size={15} className="text-[var(--text-secondary)]" />
          <input data-testid="search-chats-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t.search}
            className="bg-transparent outline-none text-sm w-full" />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 mt-3 space-y-0.5" data-testid="chat-list">
        {filtered.map((c) => (
          <div key={c.chat_id}
            className={`group flex items-center gap-2 rounded-xl px-3 py-2 cursor-pointer transition-colors ${activeId === c.chat_id ? "bg-white shadow-sm" : "hover:bg-black/[0.04]"}`}
            onClick={() => onSelect(c.chat_id)} data-testid={`chat-item-${c.chat_id}`}>
            <MessageSquare size={15} className="text-[var(--text-secondary)] flex-shrink-0" />
            <span className="flex-1 truncate text-sm">{c.title || t.newChat}</span>
            <button data-testid={`delete-chat-${c.chat_id}`}
              onClick={(e) => { e.stopPropagation(); onDelete(c.chat_id); }}
              className="opacity-0 group-hover:opacity-100 p-1 rounded hover:text-[var(--error)] transition-all">
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>

      <div className="border-t border-[var(--border-subtle)] p-3 space-y-2">
        <button data-testid="open-download-button" onClick={onDownload}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm hover:bg-black/[0.04] transition-colors">
          <Download size={16} /> {t.download}
        </button>
        <LanguageMenu lang={lang} onChange={onLang} t={t} />
        <div className="flex items-center gap-2.5 px-2 pt-1">
          {user?.picture ? (
            <img src={user.picture} alt="" className="w-8 h-8 rounded-full object-cover" />
          ) : (
            <div className="w-8 h-8 rounded-full bg-[var(--primary)] text-white flex items-center justify-center text-sm font-medium uppercase">
              {(user?.name || user?.email || "U")[0]}
            </div>
          )}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{user?.name}</p>
            <p className="text-xs text-[var(--text-secondary)] truncate">{user?.email}</p>
          </div>
          <button data-testid="logout-button" onClick={logout} className="p-2 rounded-lg hover:bg-black/5" title={t.logout}>
            <LogOut size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
