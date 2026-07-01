import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { apiPost } from "../lib/api";
import { useAuth } from "../context/AuthContext";

export default function GoogleCallback() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const hasProcessed = useRef(false);
  const [message, setMessage] = useState("Signing you in…");

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const oauthError = params.get("error");

    // Google denied access (e.g. app still in "Testing" mode, user not a test user).
    if (oauthError) {
      const msg = oauthError === "access_denied"
        ? "Google blocked the sign-in (403). Publish your Google OAuth app to Production or add your email as a Test user."
        : `Google sign-in error: ${oauthError}`;
      setMessage(msg);
      toast.error(msg);
      setTimeout(() => navigate("/login"), 2600);
      return;
    }
    if (!code) { navigate("/login"); return; }

    (async () => {
      try {
        // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
        const redirectUri = window.location.origin + "/auth/google";
        const data = await apiPost("/auth/google", { code, redirect_uri: redirectUri });
        if (data.token) localStorage.setItem("claus_token", data.token);
        setUser(data.user);
        window.history.replaceState(null, "", "/");
        navigate("/", { state: { user: data.user } });
      } catch {
        setMessage("Sign-in failed, redirecting…");
        toast.error("Google sign-in failed. Please try again.");
        setTimeout(() => navigate("/login"), 2000);
      }
    })();
  }, [navigate, setUser]);

  return (
    <div className="h-screen w-screen flex flex-col items-center justify-center gap-4 bg-[#FDFDF9] px-6 text-center">
      <div className="claus-orb animate-pulse" />
      <p className="text-[var(--text-secondary)] max-w-md" data-testid="google-callback-message">{message}</p>
    </div>
  );
}
