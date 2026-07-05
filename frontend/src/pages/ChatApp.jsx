import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Menu } from "lucide-react";
import { toast } from "sonner";
import { apiGet, apiPost, apiPatch, apiDelete, streamChat, streamRegenerate } from "../lib/api";
import { getT } from "../lib/i18n";
import { useAuth } from "../context/AuthContext";
import Sidebar from "../components/Sidebar";
import Composer from "../components/Composer";
import MessageItem from "../components/MessageItem";
import ReasoningPanel from "../components/ReasoningPanel";
import DownloadModal from "../components/DownloadModal";
import Pricing from "../components/Pricing";
import { Sparkles } from "lucide-react";

export default function ChatApp() {
  const { chatId } = useParams();
  const navigate = useNavigate();
  const { user, checkAuth } = useAuth();
  const [lang, setLang] = useState(localStorage.getItem("claus_lang") || "it");
  const t = getT(lang);
  const [chats, setChats] = useState([]);
  const [folders, setFolders] = useState([]);
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [web, setWeb] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showDownload, setShowDownload] = useState(false);
  const [showPricing, setShowPricing] = useState(false);
  const [streamingId, setStreamingId] = useState(null);
  const controllerRef = useRef(null);
  const scrollRef = useRef(null);

  const isPro = user?.plan === "pro";

  const loadChats = useCallback(async () => setChats(await apiGet("/chats").catch(() => [])), []);
  const loadFolders = useCallback(async () => setFolders(await apiGet("/folders").catch(() => [])), []);

  useEffect(() => { loadChats(); loadFolders(); }, [loadChats, loadFolders]);

  useEffect(() => {
    if (!chatId) { setMessages([]); return; }
    apiGet(`/chats/${chatId}/messages`).then((d) => setMessages(d.messages || [])).catch(() => navigate("/"));
  }, [chatId, navigate]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const setLanguage = (c) => { setLang(c); localStorage.setItem("claus_lang", c); };

  const newChat = async () => {
    const c = await apiPost("/chats");
    setChats((p) => [c, ...p]);
    setMessages([]);
    navigate(`/c/${c.chat_id}`);
    setSidebarOpen(false);
  };

  const deleteChat = async (id) => {
    await apiDelete(`/chats/${id}`);
    setChats((p) => p.filter((c) => c.chat_id !== id));
    if (id === chatId) { setMessages([]); navigate("/"); }
  };

  const renameChat = async (id, title) => {
    if (!title.trim()) return;
    setChats((p) => p.map((c) => c.chat_id === id ? { ...c, title } : c));
    await apiPatch(`/chats/${id}`, { title }).catch((e) => toast.error(e.message));
  };

  const moveChat = async (id, folderId) => {
    setChats((p) => p.map((c) => c.chat_id === id ? { ...c, folder_id: folderId } : c));
    await apiPatch(`/chats/${id}`, folderId === null ? { clear_folder: true } : { folder_id: folderId }).catch((e) => toast.error(e.message));
  };

  const createFolder = async (name) => {
    try { const f = await apiPost("/folders", { name }); setFolders((p) => [...p, f]); return f; }
    catch (e) { toast.error(e.message); }
  };
  const renameFolder = async (id, name) => {
    setFolders((p) => p.map((f) => f.folder_id === id ? { ...f, name } : f));
    await apiPatch(`/folders/${id}`, { name }).catch((e) => toast.error(e.message));
  };
  const deleteFolder = async (id) => {
    await apiDelete(`/folders/${id}`);
    setFolders((p) => p.filter((f) => f.folder_id !== id));
    setChats((p) => p.map((c) => c.folder_id === id ? { ...c, folder_id: null } : c));
  };

  const limitReached = user && user.usage_used >= user.usage_limit;

  const handleSend = async (payload) => {
    if (limitReached) { setShowPricing(true); toast.error(t.limitReached); return; }
    let activeChatId = chatId;
    if (!activeChatId) {
      const c = await apiPost("/chats");
      setChats((p) => [c, ...p]);
      activeChatId = c.chat_id;
      navigate(`/c/${c.chat_id}`);
    }
    const userMsg = { id: "u" + Date.now(), role: "user", type: "text", content: payload.content, attachments: payload.attachmentsMeta };
    const asstId = "a" + Date.now();
    const asstMsg = { id: asstId, role: "assistant", type: payload.mode === "image" ? "image" : "text", content: "", image_url: "" };
    setMessages((p) => [...p, userMsg, asstMsg]);
    setBusy(true);
    setStreamingId(asstId);

    controllerRef.current = streamChat(activeChatId, {
      content: payload.content, images: payload.images, files: payload.files,
      mode: payload.mode, web: payload.web, language: lang,
    }, {
      onDelta: (chunk) => setMessages((p) => p.map((m) => m.id === asstId ? { ...m, content: m.content + chunk } : m)),
      onImage: (evt) => setMessages((p) => p.map((m) => m.id === asstId ? { ...m, type: "image", image_url: evt.url, content: evt.text || "" } : m)),
      onDone: (evt) => {
        setBusy(false); setStreamingId(null);
        if (evt?.title) setChats((p) => p.map((c) => c.chat_id === activeChatId ? { ...c, title: evt.title } : c));
        loadChats(); checkAuth();
      },
      onError: (e) => {
        setBusy(false); setStreamingId(null);
        if (e?.status === 402) { setShowPricing(true); setMessages((p) => p.filter((m) => m.id !== asstId && m.id !== userMsg.id)); checkAuth(); return; }
        setMessages((p) => p.map((m) => m.id === asstId ? { ...m, content: m.content || "Connection error. Please try again." } : m));
      },
    });
  };

  const handleRegenerate = async () => {
    if (!chatId || busy) return;
    let base = messages;
    if (base.length && base[base.length - 1].role === "assistant") base = base.slice(0, -1);
    const asstId = "a" + Date.now();
    setMessages([...base, { id: asstId, role: "assistant", type: "text", content: "" }]);
    setBusy(true);
    setStreamingId(asstId);
    controllerRef.current = streamRegenerate(chatId, { web, language: lang }, {
      onDelta: (chunk) => setMessages((p) => p.map((m) => m.id === asstId ? { ...m, content: m.content + chunk } : m)),
      onDone: () => { setBusy(false); setStreamingId(null); loadChats(); },
      onError: () => {
        setBusy(false); setStreamingId(null);
        setMessages((p) => p.map((m) => m.id === asstId ? { ...m, content: m.content || "Connection error." } : m));
      },
    });
  };

  const stop = () => { controllerRef.current?.abort(); setBusy(false); setStreamingId(null); };

  const empty = messages.length === 0;
  const lastAssistantId = [...messages].reverse().find((m) => m.role === "assistant" && m.type === "text")?.id;
  const streamingMsg = streamingId ? messages.find((m) => m.id === streamingId) : null;
  const showThinking = streamingMsg && streamingMsg.content === "" && streamingMsg.type !== "image";

  const sidebarProps = {
    chats, folders, activeId: chatId, onNew: newChat, onDelete: deleteChat,
    onRename: renameChat, onMove: moveChat, onNewFolder: createFolder,
    onRenameFolder: renameFolder, onDeleteFolder: deleteFolder,
    lang, onLang: setLanguage, t, onDownload: () => setShowDownload(true),
    user, onUpgrade: () => setShowPricing(true),
  };

  return (
    <div className="h-screen w-screen flex overflow-hidden bg-[var(--bg-main)]">
      <div className="hidden lg:block flex-shrink-0">
        <Sidebar {...sidebarProps} onSelect={(id) => navigate(`/c/${id}`)} onClose={() => {}} />
      </div>
      {sidebarOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div className="flex-shrink-0">
            <Sidebar {...sidebarProps}
              onSelect={(id) => { navigate(`/c/${id}`); setSidebarOpen(false); }}
              onClose={() => setSidebarOpen(false)}
              onDownload={() => { setShowDownload(true); setSidebarOpen(false); }}
              onUpgrade={() => { setShowPricing(true); setSidebarOpen(false); }} />
          </div>
          <div className="flex-1 bg-black/30" onClick={() => setSidebarOpen(false)} />
        </div>
      )}

      <div className="flex-1 flex flex-col min-w-0">
        <header className="flex items-center justify-between px-4 h-14 border-b border-[var(--border-subtle)] lg:border-none">
          <div className="flex items-center gap-3">
            <button onClick={() => setSidebarOpen(true)} className="lg:hidden p-2 rounded-lg hover:bg-black/5"><Menu size={20} /></button>
            <span className="lg:hidden font-serif text-lg">Claus IA</span>
          </div>
          {!isPro && (
            <button data-testid="header-upgrade-button" onClick={() => setShowPricing(true)}
              className="flex items-center gap-1.5 text-sm bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-full px-4 py-1.5 transition-colors">
              <Sparkles size={14} /> {t.upgrade}
            </button>
          )}
          {isPro && <span className="text-sm font-medium text-[var(--primary)] flex items-center gap-1"><Sparkles size={14} /> Pro</span>}
        </header>

        {empty ? (
          <div className="flex-1 flex flex-col items-center justify-center px-4">
            <div className="w-full max-w-3xl fade-up">
              <div className="flex flex-col items-center text-center mb-10">
                <div className="claus-orb mb-5" style={{ width: 56, height: 56 }} />
                <h1 className="font-serif text-4xl sm:text-5xl tracking-tight">{t.greeting}</h1>
              </div>
              <Composer onSend={handleSend} busy={busy} onStop={stop} web={web} setWeb={setWeb} t={t} lang={lang} />
              <div className="flex flex-wrap gap-2 justify-center mt-6 max-w-2xl mx-auto">
                {t.sugg.map((s, i) => (
                  <button key={i} data-testid={`suggestion-${i}`} onClick={() => handleSend({ content: s, images: [], files: [], mode: "chat", web, attachmentsMeta: [] })}
                    className="flex items-center gap-2 text-sm border border-[var(--border-subtle)] bg-white rounded-full px-4 py-2 hover:border-[var(--primary)] hover:text-[var(--primary)] transition-colors">
                    <Sparkles size={14} /> {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <>
            <div ref={scrollRef} className="flex-1 overflow-y-auto" data-testid="messages-container">
              <div className="max-w-3xl mx-auto px-4 py-8 space-y-7">
                {messages.map((m) => (
                  <MessageItem key={m.id} message={m}
                    isStreaming={streamingId === m.id && !m.content && m.type !== "image"}
                    canRegenerate={!busy && m.id === lastAssistantId}
                    onRegenerate={handleRegenerate} t={t} />
                ))}
                {showThinking && (isPro ? (
                  <ReasoningPanel steps={t.reasoningSteps} label={t.advancedReasoning} />
                ) : (
                  <div className="flex gap-4">
                    <div className="claus-orb flex-shrink-0" style={{ width: 30, height: 30 }} />
                    <p className="text-[var(--text-secondary)] italic mt-1">{t.thinking}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="pb-4 pt-2">
              <Composer onSend={handleSend} busy={busy} onStop={stop} web={web} setWeb={setWeb} t={t} lang={lang} />
            </div>
          </>
        )}
      </div>

      <DownloadModal open={showDownload} onClose={() => setShowDownload(false)} t={t} />
      <Pricing open={showPricing} onClose={() => setShowPricing(false)} t={t} lang={lang} user={user} onUpgraded={checkAuth} />
    </div>
  );
}
