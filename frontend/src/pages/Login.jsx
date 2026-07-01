import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Mail, ArrowRight, ArrowLeft, Loader2 } from "lucide-react";
import { apiPost } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { getT } from "../lib/i18n";
import LanguageMenu from "../components/LanguageMenu";

const AUTH_BG = "https://images.pexels.com/photos/5506215/pexels-photo-5506215.jpeg";

export default function Login() {
  const [lang, setLang] = useState(localStorage.getItem("claus_lang") || "it");
  const t = getT(lang);
  const [step, setStep] = useState("welcome"); // welcome | email | otp
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const { setUser } = useAuth();
  const navigate = useNavigate();

  const handleLang = (c) => { setLang(c); localStorage.setItem("claus_lang", c); };

  const googleLogin = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + "/";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  const sendCode = async () => {
    if (!email.includes("@")) return toast.error("Enter a valid email");
    setBusy(true);
    try {
      await apiPost("/auth/otp/request", { email });
      setStep("otp");
      toast.success(t.otpSub + " " + email);
    } catch (e) { toast.error(e.message); }
    setBusy(false);
  };

  const verify = async () => {
    if (code.length < 6) return toast.error("Enter the 6-digit code");
    setBusy(true);
    try {
      const data = await apiPost("/auth/otp/verify", { email, code });
      if (data.token) localStorage.setItem("claus_token", data.token);
      setUser(data.user);
      navigate("/");
    } catch (e) { toast.error(e.message); }
    setBusy(false);
  };

  return (
    <div className="h-screen w-screen flex bg-[#FDFDF9] overflow-hidden">
      {/* Left visual */}
      <div className="hidden lg:block lg:w-1/2 relative">
        <img src={AUTH_BG} alt="" className="absolute inset-0 w-full h-full object-cover" />
        <div className="absolute inset-0 bg-gradient-to-t from-[#2D2A26]/55 via-[#2D2A26]/15 to-transparent" />
        <div className="absolute bottom-12 left-12 right-12 text-white">
          <div className="flex items-center gap-3 mb-5">
            <div className="claus-orb" style={{ width: 38, height: 38 }} />
            <span className="font-serif text-2xl">Claus IA</span>
          </div>
          <h2 className="font-serif text-4xl leading-tight max-w-md">{t.welcome}</h2>
        </div>
      </div>

      {/* Right form */}
      <div className="flex-1 flex flex-col">
        <div className="flex justify-end p-5">
          <LanguageMenu lang={lang} onChange={handleLang} t={t} />
        </div>
        <div className="flex-1 flex items-center justify-center px-6 pb-16">
          <div className="w-full max-w-sm fade-up">
            <div className="lg:hidden flex items-center gap-3 mb-8">
              <div className="claus-orb" style={{ width: 36, height: 36 }} />
              <span className="font-serif text-2xl">Claus IA</span>
            </div>

            {step === "welcome" && (
              <div>
                <h1 className="font-serif text-4xl tracking-tight mb-2">Claus IA</h1>
                <p className="text-[var(--text-secondary)] mb-8">{t.welcomeSub}</p>
                <button data-testid="login-google-button" onClick={googleLogin}
                  className="w-full flex items-center justify-center gap-3 border border-[var(--border-subtle)] bg-white rounded-full py-3 px-4 font-medium hover:bg-black/[0.03] transition-colors">
                  <GoogleIcon /> {t.withGoogle}
                </button>
                <div className="flex items-center gap-3 my-5 text-[var(--text-secondary)] text-sm">
                  <div className="h-px flex-1 bg-[var(--border-subtle)]" /> {t.or} <div className="h-px flex-1 bg-[var(--border-subtle)]" />
                </div>
                <button data-testid="login-email-button" onClick={() => setStep("email")}
                  className="w-full flex items-center justify-center gap-3 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-full py-3 px-4 font-medium transition-colors">
                  <Mail size={18} strokeWidth={1.8} /> {t.withEmail}
                </button>
              </div>
            )}

            {step === "email" && (
              <div className="fade-up">
                <button onClick={() => setStep("welcome")} className="flex items-center gap-1 text-sm text-[var(--text-secondary)] mb-6 hover:text-[var(--text-primary)]">
                  <ArrowLeft size={16} /> {t.back}
                </button>
                <h1 className="font-serif text-3xl mb-2">{t.withEmail}</h1>
                <p className="text-[var(--text-secondary)] mb-6">{t.welcomeSub}</p>
                <label className="text-sm font-medium">{t.email}</label>
                <input data-testid="login-email-input" type="email" value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendCode()}
                  placeholder="name@email.com" autoFocus
                  className="w-full mt-2 mb-5 rounded-xl border border-[var(--border-subtle)] bg-white px-4 py-3 outline-none focus:border-[var(--primary)] transition-colors" />
                <button data-testid="send-code-button" onClick={sendCode} disabled={busy}
                  className="w-full flex items-center justify-center gap-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-full py-3 font-medium transition-colors disabled:opacity-60">
                  {busy ? <Loader2 size={18} className="animate-spin" /> : <>{t.sendCode} <ArrowRight size={18} /></>}
                </button>
              </div>
            )}

            {step === "otp" && (
              <div className="fade-up">
                <button onClick={() => setStep("email")} className="flex items-center gap-1 text-sm text-[var(--text-secondary)] mb-6 hover:text-[var(--text-primary)]">
                  <ArrowLeft size={16} /> {t.back}
                </button>
                <h1 className="font-serif text-3xl mb-2">{t.otpTitle}</h1>
                <p className="text-[var(--text-secondary)] mb-6">{t.otpSub} <span className="font-medium text-[var(--text-primary)]">{email}</span></p>
                <input data-testid="otp-input-field" inputMode="numeric" maxLength={6} value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  onKeyDown={(e) => e.key === "Enter" && verify()}
                  placeholder="••••••" autoFocus
                  className="w-full mb-5 rounded-xl border border-[var(--border-subtle)] bg-white px-4 py-3 text-center text-2xl tracking-[0.5em] font-mono outline-none focus:border-[var(--primary)] transition-colors" />
                <button data-testid="verify-otp-button" onClick={verify} disabled={busy}
                  className="w-full flex items-center justify-center gap-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-full py-3 font-medium transition-colors disabled:opacity-60">
                  {busy ? <Loader2 size={18} className="animate-spin" /> : t.verify}
                </button>
                <button onClick={sendCode} className="w-full text-sm text-[var(--text-secondary)] mt-4 hover:text-[var(--primary)]">{t.resend}</button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.4 29.3 35 24 35c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.5 5.1 29.5 3 24 3 11.8 3 2 12.8 2 25s9.8 22 22 22c11 0 21-8 21-22 0-1.3-.1-2.7-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 16 19 13 24 13c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.5 7.1 29.5 5 24 5 16.3 5 9.7 9.3 6.3 14.7z" transform="translate(0 -2)"/><path fill="#4CAF50" d="M24 45c5.2 0 10-2 13.6-5.2l-6.3-5.3C29.2 36 26.7 37 24 37c-5.3 0-9.7-3.4-11.3-8.1l-6.5 5C9.5 39.6 16.2 45 24 45z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.1-4 5.5l6.3 5.3C41.4 36 45 30.9 45 24c0-1.3-.1-2.7-.4-3.5z"/></svg>
  );
}
