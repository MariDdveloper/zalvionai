import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Menu, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { apiGet, apiPost, apiDelete, streamChat } from "../lib/api";
import { getT } from "../lib/i18n";
import Sidebar from "../components/Sidebar";
import Composer from "../components/Composer";
import MessageItem from "../components/MessageItem";
import DownloadModal from "../components/DownloadModal";

export default function ChatApp() {
  const { chatId } = useParams();
  const navigate = useNavigate();
  const [lang, setLang] = useState(localStorage.getItem("claus_lang") || "it");
  const t = getT(lang);
  const [chats, setChats] = useState([]);
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [web, setWeb] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showDownload, setShowDownload] = useState(false);
  const [streamingId, setStreamingId] = useState(null);
  const controllerRef = useRef(null);
  const scrollRef = useRef(null);

  const loadChats = useCallback(async () => {
    const data = await apiGet("/chats").catch(() => []);
    setChats(data);
  }, []);

  useEffect(() => { loadChats(); }, [loadChats]);

  useEffect(() => {
    if (!chatId) { setMessages([]); return; }
    apiGet(`/chats/${chatId}/messages`).then((d) => setMessages(d.messages || [])).catch(() => navigate("/"));
  }, [chatId, navigate]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // Poll while a video is generating
  useEffect(() => {
    if (!chatId) return;
    const hasGenerating = messages.some((m) => m.type === "video" && m.status === "generating");
    if (!hasGenerating) return;
    const iv = setInterval(async () => {
      const d = await apiGet(`/chats/${chatId}/messages`).catch(() => null);
      if (d?.messages) setMessages(d.messages);
    }, 5000);
    return () => clearInterval(iv);
  }, [messages, chatId]);

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

  const handleVideo = async (payload) => {
    let activeChatId = chatId;
    if (!activeChatId) {
      const c = await apiPost("/chats");
      setChats((p) => [c, ...p]);
      activeChatId = c.chat_id;
      navigate(`/c/${c.chat_id}`);
    }
    setBusy(true);
    try {
      await apiPost(`/chats/${activeChatId}/video`, {
        content: payload.content,
        size: payload.size || "1280x720",
        duration: payload.duration || 4,
        image: payload.image || null,
        language: lang,
      });
      const d = await apiGet(`/chats/${activeChatId}/messages`);
      setMessages(d.messages || []);
      loadChats();
    } catch (e) {
      toast.error(e.message || "Video generation error");
    }
    setBusy(false);
  };

  const handleSend = async (payload) => {
    if (payload.mode === "video") return handleVideo(payload);
    let activeChatId = chatId;
    if (!activeChatId) {
      const c = await apiPost("/chats");
      setChats((p) => [c, ...p]);
      activeChatId = c.chat_id;
      navigate(`/c/${c.chat_id}`);
    }

    const userMsg = {
      id: "u" + Date.now(), role: "user", type: "text",
      content: payload.content, attachments: payload.attachmentsMeta,
    };
    const asstId = "a" + Date.now();
    const asstMsg = { id: asstId, role: "assistant", type: payload.mode === "image" ? "image" : "text", content: "", image_url: "" };
    setMessages((p) => [...p, userMsg, asstMsg]);
    setBusy(true);
    setStreamingId(asstId);

    controllerRef.current = streamChat(activeChatId, {
      content: payload.content, images: payload.images, files: payload.files,
      mode: payload.mode, web: payload.web, language: lang,
    }, {
      onDelta: (chunk) => {
        setMessages((p) => p.map((m) => m.id === asstId ? { ...m, content: m.content + chunk } : m));
      },
      onImage: (evt) => {
        setMessages((p) => p.map((m) => m.id === asstId ? { ...m, type: "image", image_url: evt.url, content: evt.text || "" } : m));
      },
      onDone: (evt) => {
        setBusy(false);
        setStreamingId(null);
        if (evt?.title) setChats((p) => p.map((c) => c.chat_id === activeChatId ? { ...c, title: evt.title } : c));
        loadChats();
      },
      onError: () => {
        setBusy(false);
        setStreamingId(null);
        setMessages((p) => p.map((m) => m.id === asstId ? { ...m, content: m.content || "Connection error. Please try again." } : m));
      },
    });
  };

  const stop = () => { controllerRef.current?.abort(); setBusy(false); setStreamingId(null); };

  const empty = messages.length === 0;

  return (
    <div className="h-screen w-screen flex overflow-hidden bg-[var(--bg-main)]">
      {/* Sidebar desktop */}
      <div className="hidden lg:block flex-shrink-0">
        <Sidebar chats={chats} activeId={chatId} onNew={newChat} onSelect={(id) => navigate(`/c/${id}`)}
          onDelete={deleteChat} onClose={() => {}} lang={lang} onLang={setLanguage} t={t} onDownload={() => setShowDownload(true)} />
      </div>
      {/* Sidebar mobile */}
      {sidebarOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div className="flex-shrink-0"><Sidebar chats={chats} activeId={chatId} onNew={newChat} onSelect={(id) => { navigate(`/c/${id}`); setSidebarOpen(false); }}
            onDelete={deleteChat} onClose={() => setSidebarOpen(false)} lang={lang} onLang={setLanguage} t={t} onDownload={() => { setShowDownload(true); setSidebarOpen(false); }} /></div>
          <div className="flex-1 bg-black/30" onClick={() => setSidebarOpen(false)} />
        </div>
      )}

      <div className="flex-1 flex flex-col min-w-0">
        <header className="flex items-center gap-3 px-4 h-14 border-b border-[var(--border-subtle)] lg:border-none">
          <button onClick={() => setSidebarOpen(true)} className="lg:hidden p-2 rounded-lg hover:bg-black/5"><Menu size={20} /></button>
          <span className="lg:hidden font-serif text-lg">Claus IA</span>
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
                  <MessageItem key={m.id} message={m} isStreaming={streamingId === m.id && !m.content && m.type !== "image"} />
                ))}
                {streamingId && messages.find((m) => m.id === streamingId)?.content === "" && messages.find((m) => m.id === streamingId)?.type !== "image" && (
                  <div className="flex gap-4">
                    <div className="claus-orb flex-shrink-0" style={{ width: 30, height: 30 }} />
                    <p className="text-[var(--text-secondary)] italic mt-1">{t.thinking}</p>
                  </div>
                )}
              </div>
            </div>
            <div className="pb-4 pt-2">
              <Composer onSend={handleSend} busy={busy} onStop={stop} web={web} setWeb={setWeb} t={t} lang={lang} />
            </div>
          </>
        )}
      </div>

      <DownloadModal open={showDownload} onClose={() => setShowDownload(false)} t={t} />
    </div>
  );
}
