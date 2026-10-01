"use client";

import { FormEvent, useEffect, useState } from "react";
import "./settings.css";

const API = "";
const STORAGE_KEY = "studio-personal-ark-key";

type AuthUser = { phone?: string; display_name?: string };

function maskKey(value: string) {
  const trimmed = value.trim();
  if (trimmed.length < 10) return "已配置个人 API Key";
  return `${trimmed.slice(0, 4)}${"•".repeat(Math.min(12, trimmed.length - 8))}${trimmed.slice(-4)}`;
}

function errorMessage(payload: { detail?: unknown; message?: unknown }, fallback: string) {
  if (typeof payload.message === "string") return payload.message;
  if (typeof payload.detail === "string") return payload.detail;
  if (payload.detail && typeof payload.detail === "object" && "message" in payload.detail && typeof payload.detail.message === "string") {
    return payload.detail.message;
  }
  return fallback;
}

export default function SettingsPage() {
  const [key, setKey] = useState("");
  const [keyHint, setKeyHint] = useState("");
  const [configured, setConfigured] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState("");
  const [statusKind, setStatusKind] = useState<"success" | "error" | "">("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const stored = sessionStorage.getItem(STORAGE_KEY) || "";
    if (stored) {
      window.queueMicrotask(() => {
        setConfigured(true);
        setKeyHint(maskKey(stored));
      });
    }

    fetch(`${API}/api/auth/me`, { credentials: "include", cache: "no-store" })
      .then((response) => response.ok ? response.json() : null)
      .then((data: { authenticated?: boolean; user?: AuthUser } | null) => {
        if (data?.authenticated && data.user) setUser(data.user);
      })
      .catch(() => undefined);
  }, []);

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const candidate = key.trim();
    if (candidate.length < 20) {
      setStatusKind("error");
      setStatus("请输入完整的 API Key");
      return;
    }

    setSaving(true);
    setStatus("");
    setStatusKind("");
    try {
      const response = await fetch(`${API}/api/access/verify-user-key`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: candidate }),
      });
      const payload = await response.json().catch(() => ({})) as { ok?: boolean; detail?: unknown; message?: unknown };
      if (!response.ok || !payload.ok) throw new Error(errorMessage(payload, "API Key 验证未通过，请检查后重试"));

      sessionStorage.setItem(STORAGE_KEY, candidate);
      sessionStorage.removeItem("studio-personal-plan-key");
      setConfigured(true);
      setKeyHint(maskKey(candidate));
      setKey("");
      setStatusKind("success");
      setStatus("API Key 已验证并保存在当前浏览器会话中");
    } catch (error) {
      setStatusKind("error");
      setStatus(error instanceof Error ? error.message : "API Key 验证失败，请稍后重试");
    } finally {
      setSaving(false);
    }
  };

  const clearKey = () => {
    sessionStorage.removeItem(STORAGE_KEY);
    sessionStorage.removeItem("studio-personal-plan-key");
    setConfigured(false);
    setKeyHint("");
    setKey("");
    setStatusKind("success");
    setStatus("已清除当前浏览器会话中的个人 API Key");
  };

  return (
    <main className="settings-page">
      <nav className="settings-page__nav">
        <a href="/dashboard">← 返回工作台</a>
        <span>家纺 AI 视觉</span>
      </nav>

      <div className="settings-page__content">
        <header className="settings-page__header">
          <p className="settings-page__eyebrow">PERSONAL SETTINGS</p>
          <h1>个人设置</h1>
          <p>{user?.display_name || user?.phone || "配置你的创作服务"}</p>
        </header>

        <section className="settings-card" aria-labelledby="api-key-title">
          <div className="settings-card__heading">
            <div>
              <p className="settings-card__eyebrow">BYOK</p>
              <h2 id="api-key-title">个人 API Key</h2>
            </div>
            <span className={`settings-status-dot${configured ? " is-on" : ""}`} aria-label={configured ? "已配置" : "未配置"} />
          </div>
          <p className="settings-card__intro">使用自己的火山方舟 Key 进行图片生成。Key 只保存在当前浏览器会话中，退出登录或清除后需要重新验证。</p>

          {configured && (
            <div className="settings-key-status" role="status">
              <span>当前状态</span>
              <strong>{keyHint}</strong>
            </div>
          )}

          <form className="settings-form" onSubmit={save}>
            <label htmlFor="personal-api-key">输入新的 API Key</label>
            <input
              id="personal-api-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={key}
              onChange={(event) => setKey(event.target.value)}
              placeholder={configured ? "输入新 Key 以替换当前配置" : "粘贴你的火山方舟 API Key"}
              minLength={20}
              required
            />
            <button type="submit" disabled={saving || key.trim().length < 20}>
              {saving ? "正在验证…" : configured ? "验证并替换" : "验证并保存"}
            </button>
          </form>

          {configured && (
            <button className="settings-clear" type="button" onClick={clearKey}>
              清除个人 API Key
            </button>
          )}
          {status && <p className={`settings-message settings-message--${statusKind}`} role={statusKind === "error" ? "alert" : "status"}>{status}</p>}
        </section>

        <a className="settings-page__back" href="/dashboard">返回工作台 →</a>
      </div>
    </main>
  );
}
