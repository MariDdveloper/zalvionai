import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { apiPost } from "../lib/api";
import { useAuth } from "../context/AuthContext";

export default function AuthCallback() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const hasProcessed = useRef(false);

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;
    const hash = window.location.hash || "";
    const match = hash.match(/session_id=([^&]+)/);
    const sessionId = match ? decodeURIComponent(match[1]) : null;
    if (!sessionId) { navigate("/login"); return; }
    (async () => {
      try {
        const data = await apiPost("/auth/google/session", null, { "X-Session-ID": sessionId });
        if (data.token) localStorage.setItem("claus_token", data.token);
        setUser(data.user);
        window.history.replaceState(null, "", "/");
        navigate("/", { state: { user: data.user } });
      } catch {
        navigate("/login");
      }
    })();
  }, [navigate, setUser]);

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-[#FDFDF9]">
      <div className="claus-orb animate-pulse" />
    </div>
  );
}
