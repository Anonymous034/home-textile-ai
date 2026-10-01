"use client";

import { FormEvent, useState } from "react";
import "./setup-key.css";

const API = (process.env.NEXT_PUBLIC_STUDIO_API ?? "").replace(/\/+$/, "");

export default function SetupKeyPage() {
  const [key, setKey] = useState("");
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setStatus("");
    try {
      const response = await fetch(`${API}/api/local-config/ark-key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: key.trim() }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "保存失败");
      setKey("");
      setStatus("保存成功，真实 AI 生成服务已经启用。现在可以进入虚拟影棚。");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "保存失败，请重试");
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="key-setup-page">
      <section className="key-setup-card">
        <span className="key-setup-tag">LOCAL SECURITY SETUP</span>
        <h1>配置 AI 生图密钥</h1>
        <p>请使用一把全新、没有发到聊天中的 Agent Plan API Key。它只会保存到你电脑的后端，不会进入网页代码或数据库。</p>
        <form onSubmit={save}>
          <label htmlFor="ark-key">Agent Plan API Key</label>
          <input
            id="ark-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={key}
            onChange={(event) => setKey(event.target.value)}
            placeholder="粘贴 API Key 管理页面复制的完整原始值"
            required
            minLength={20}
          />
          <button type="submit" disabled={saving || key.trim().length < 20}>
            {saving ? "正在安全保存..." : "安全保存并启用"}
          </button>
        </form>
        {status && <output className="key-setup-status">{status}</output>}
        <a href="/studio">返回 AI 虚拟影棚 →</a>
      </section>
    </main>
  );
}
