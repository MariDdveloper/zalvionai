import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiPost } from "../lib/api";
import { useAuth } from "../context/AuthContext";

export default function GoogleCallback() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const hasProcessed = useRef(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
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
        setError(true);
        setTimeout(() => navigate("/login"), 1800);
      }
    })();
  }, [navigate, setUser]);

  return (
    <div className="h-screen w-screen flex flex-col items-center justify-center gap-4 bg-[#FDFDF9]">
      <div className="claus-orb animate-pulse" />
      <p className="text-[var(--text-secondary)]">
        {error ? "Sign-in failed, redirecting…" : "Signing you in…"}
      </p>
    </div>
  );
}
