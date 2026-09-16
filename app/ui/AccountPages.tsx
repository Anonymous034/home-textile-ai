"use client";

import { useEffect, useState } from "react";
import "./AccountPages.css";

const API = process.env.NEXT_PUBLIC_STUDIO_API ?? "http://127.0.0.1:8000";

type Work = { id: string; tool_name: string; created_at: string; image_url: string };
type CreditEvent = { id: string; delta: number; reason: string; created_at: string };
type PendingUsage = { id: string; points: number; reason: string; created_at: string };

function WorkCard({ work }: { work: Work }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    fetch(API + work.image_url, { cache: "no-store" }).then((response) => {
      if (!response.ok) throw new Error("作品文件不可用");
      return response.blob();
    }).then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      if (active) setSrc(objectUrl);
      else URL.revokeObjectURL(objectUrl);
    }).catch(() => undefined);
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [work.image_url]);
  return <article className="account-work-card">
    <div className="account-work-card__image">{src ? <img src={src} alt={`${work.tool_name}生成作品`} /> : <span>图片加载中或已过期</span>}</div>
    <div className="account-work-card__meta"><strong>{work.tool_name}</strong><time>{new Date(work.created_at).toLocaleString("zh-CN")}</time></div>
    {src && <a href={src} download={`${work.tool_name}-${work.id}.png`}>下载作品</a>}
  </article>;
}

export function MyWorksPage() {
  const [works, setWorks] = useState<Work[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(`${API}/api/account/works`, { cache: "no-store" })
      .then(async (response) => { if (!response.ok) throw new Error("作品列表加载失败"); return response.json(); })
      .then((data) => setWorks(data.items ?? []))
      .catch((reason) => setError(reason instanceof Error ? reason.message : "作品列表加载失败"))
      .finally(() => setLoading(false));
  }, []);
  return <main className="account-page">
    <header><a href="/dashboard">← 返回功能页</a><h1>我的作品</h1><p>查看当前账号在本机生成并保存的图片。</p></header>
    {loading ? <p role="status">正在读取作品…</p> : error ? <p role="alert">{error}</p> : works.length ? <div className="account-work-grid">{works.map((work) => <WorkCard work={work} key={work.id} />)}</div> : <div className="account-empty">暂无已保存的生成作品</div>}
  </main>;
}

export function CreditsPage() {
  const [balance, setBalance] = useState<number | null>(null);
  const [events, setEvents] = useState<CreditEvent[]>([]);
  const [pending, setPending] = useState<PendingUsage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(`${API}/api/account/credits`, { cache: "no-store" })
      .then(async (response) => { if (!response.ok) throw new Error("积分记录加载失败"); return response.json(); })
      .then((data) => { setBalance(data.balance); setEvents(data.events ?? []); setPending(data.pending_usage ?? []); })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "积分记录加载失败"))
      .finally(() => setLoading(false));
  }, []);
  return <main className="account-page account-page--credits">
    <header><a href="/dashboard">← 返回功能页</a><h1>积分中心</h1><p>查看当前账号的积分余额与扣除记录。</p></header>
    {loading ? <p role="status">正在读取积分…</p> : error ? <p role="alert">{error}</p> : <>
      <section className="account-balance"><span>剩余积分</span><strong>{balance === null ? "未配置" : balance}</strong><small>{balance === null ? "本站尚未设置积分余额，目前不会实际扣除积分。" : "分"}</small></section>
      <section className="account-history"><h2>扣除记录</h2>{events.length ? <ul>{events.map((event) => <li key={event.id}><div><strong>{event.reason}</strong><time>{new Date(event.created_at).toLocaleString("zh-CN")}</time></div><b>{event.delta}</b></li>)}</ul> : <p>暂无扣除记录</p>}</section>
      <section className="account-history"><h2>生成使用记录</h2><p>按功能页面标注的单张积分估算；余额未配置时不实际扣费。</p>{pending.length ? <ul>{pending.map((item) => <li key={item.id}><div><strong>{item.reason}</strong><time>{new Date(item.created_at).toLocaleString("zh-CN")}</time></div><b>预计 {item.points} 分</b></li>)}</ul> : <p>暂无已保存的对应作品</p>}</section>
    </>}
  </main>;
}
