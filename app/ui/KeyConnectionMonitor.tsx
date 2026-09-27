"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_STUDIO_API ?? "http://127.0.0.1:8000";

type Status = "checking" | "connected" | "stable" | "failed";

export default function KeyConnectionMonitor() {
  const [enabled, setEnabled] = useState(false);
  const [status, setStatus] = useState<Status>("checking");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!sessionStorage.getItem("studio-personal-ark-key")) return;
    setEnabled(true);
    let active = true;
    const check = async () => {
      try {
        const response = await fetch(`${API}/api/access/key-status`, { cache: "no-store" });
        const body = await response.json();
        if (!active) return;
        if (!response.ok) {
          setStatus("failed");
          setMessage(typeof body.detail === "string" ? body.detail : body.detail?.message ?? "密钥或网络暂不可用");
          return;
        }
        setStatus(body.stable ? "stable" : "connected");
        setMessage(body.stable ? "个人 API Key 连续 3 次探测通过" : "个人 API Key 已连通，持续检测中");
      } catch {
        if (active) { setStatus("failed"); setMessage("本地服务暂不可连接"); }
      }
    };
    void check();
    const timer = window.setInterval(() => { void check(); }, 15000);
    const visible = () => { if (document.visibilityState === "visible") void check(); };
    document.addEventListener("visibilitychange", visible);
    return () => { active = false; window.clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, []);

  if (!enabled) return null;
  return <div className={`key-health key-health--${status}`} role="status" aria-live="polite"><i aria-hidden="true" />{message || "正在检查个人 API Key…"}</div>;
}
