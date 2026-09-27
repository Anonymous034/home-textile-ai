"use client";

import { useEffect, useMemo, useState } from "react";
import "./RechargePage.css";

const API = process.env.NEXT_PUBLIC_STUDIO_API ?? "http://127.0.0.1:8000";
const STORAGE_KEY = "studio-payment-order";

type PackageId = "starter" | "popular" | "pro" | "custom";
type OrderStatus = "pending" | "succeeded" | "cancelled" | "expired";
type PaymentOrder = {
  id: string; amount_cents: number; points: number; package_id: string | null; package_name: string;
  is_custom: boolean; status: OrderStatus; provider: "mock" | "alipay";
  environment: "mock" | "sandbox" | "production"; payment_mode: string; checkout_url: string | null;
  created_at: string; completed_at: string | null; expires_at: string;
};

const packages = [
  { id: "starter" as const, amount: 199, points: 2200, name: "轻享包", note: "适合体验与少量创作" },
  { id: "popular" as const, amount: 480, points: 6600, name: "进阶包", note: "额外赠送 1,800 积分", badge: "推荐" },
  { id: "pro" as const, amount: 1440, points: 26400, name: "专业包", note: "额外赠送 12,000 积分" },
];

async function apiRequest(path: string, options?: RequestInit) {
  let response: Response;
  try { response = await fetch(`${API}${path}`, { cache: "no-store", ...options }); }
  catch { throw new Error("无法连接支付服务，请稍后重试或联系管理员。"); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : data.detail?.message;
    throw new Error(detail || "支付接口请求失败，请稍后重试。");
  }
  return data;
}

const money = (cents: number) => (cents / 100).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
function SuccessIcon() { return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m5 12.5 4.2 4.2L19 7" /></svg>; }

export default function RechargePage() {
  const [selection, setSelection] = useState<PackageId>("popular");
  const [customAmount, setCustomAmount] = useState("100");
  const [order, setOrder] = useState<PaymentOrder | null>(null);
  const [balance, setBalance] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [remaining, setRemaining] = useState(0);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("alipay_return") === "invalid") setError("支付宝返回参数验签失败。订单不会入账，请返回支付宝确认结果或稍后刷新状态。");
    const savedOrder = params.get("order_id") || sessionStorage.getItem(STORAGE_KEY);
    if (!savedOrder) return;
    let active = true;
    setBusy(true);
    (async () => {
      try {
        let data = await apiRequest(`/api/account/payment-orders/${encodeURIComponent(savedOrder)}`);
        if (params.get("alipay_return") === "1" && data.order.provider === "alipay" && data.order.status !== "succeeded") {
          setStatusMessage("已返回网站，正在向支付宝核对订单…");
          data = await apiRequest(`/api/account/payment-orders/${encodeURIComponent(savedOrder)}/sync`, { method: "POST" });
        }
        if (!active) return;
        setOrder(data.order); sessionStorage.setItem(STORAGE_KEY, data.order.id);
        setStatusMessage(data.order.status === "succeeded" ? "支付宝订单已确认，积分已经到账。" : "订单已恢复，正在等待支付结果。");
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "订单恢复失败");
      } finally { if (active) setBusy(false); }
    })();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!order || order.status !== "pending") return;
    const tick = () => setRemaining(Math.max(0, Math.ceil((new Date(order.expires_at).getTime() - Date.now()) / 1000)));
    tick(); const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [order]);

  useEffect(() => {
    if (!order || order.provider !== "alipay" || order.status !== "pending") return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const data = await apiRequest(`/api/account/payment-orders/${encodeURIComponent(order.id)}`);
        if (!active) return;
        setOrder(data.order);
        if (data.order.status === "succeeded") setStatusMessage("支付宝异步通知已确认，积分已经到账。");
      } catch { /* Explicit refresh remains available as the recovery path. */ }
    }, 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [order?.id, order?.provider, order?.status]);

  useEffect(() => {
    if (order?.status !== "succeeded") return;
    apiRequest("/api/account/credits").then((data) => setBalance(data.balance)).catch(() => undefined);
  }, [order?.status]);

  const preview = useMemo(() => {
    if (selection === "custom") {
      const amount = Number(customAmount);
      return { amount: Number.isInteger(amount) ? amount : 0, points: Number.isInteger(amount) ? amount * 10 : 0, name: "自定义充值" };
    }
    return packages.find((item) => item.id === selection) ?? packages[0];
  }, [selection, customAmount]);
  const customPoints = Number.isInteger(Number(customAmount)) ? Math.max(0, Number(customAmount) * 10) : 0;
  const customHasError = error.startsWith("自定义金额");

  const createOrder = async () => {
    setError(""); setStatusMessage("");
    if (selection === "custom") {
      const amount = Number(customAmount);
      if (!Number.isInteger(amount) || amount < 1 || amount > 5000) { setError("自定义金额须为 1–5000 元的整数。"); return; }
    }
    setBusy(true);
    try {
      const body = selection === "custom" ? { custom_amount_yuan: Number(customAmount) } : { package_id: selection };
      const data = await apiRequest("/api/account/payment-orders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      setOrder(data.order); sessionStorage.setItem(STORAGE_KEY, data.order.id);
      setStatusMessage(data.order.provider === "alipay" ? "支付宝沙箱订单已创建，请前往收银台完成测试。" : "支付宝参数尚未配置，已创建本地模拟订单。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "创建支付订单失败"); }
    finally { setBusy(false); }
  };

  const completeMockOrder = async () => {
    if (!order) return; setError(""); setBusy(true);
    try {
      const data = await apiRequest(`/api/account/payment-orders/${encodeURIComponent(order.id)}/complete`, { method: "POST" });
      setOrder(data.order); setBalance(data.balance); setStatusMessage("本地模拟订单已确认，积分已经到账。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "确认支付失败"); }
    finally { setBusy(false); }
  };

  const syncOrder = async () => {
    if (!order) return; setError(""); setBusy(true); setStatusMessage("正在向支付宝查询订单状态…");
    try {
      const data = await apiRequest(`/api/account/payment-orders/${encodeURIComponent(order.id)}/sync`, { method: "POST" });
      setOrder(data.order); setBalance(data.balance ?? null);
      setStatusMessage(data.order.status === "succeeded" ? "支付宝已确认支付，积分已经到账。" : "支付宝尚未确认支付，请完成付款后再刷新。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "订单状态查询失败"); setStatusMessage(""); }
    finally { setBusy(false); }
  };

  const cancelOrder = async () => {
    if (!order) return; setError(""); setBusy(true);
    try {
      const data = await apiRequest(`/api/account/payment-orders/${encodeURIComponent(order.id)}/cancel`, { method: "POST" });
      setOrder(data.order); sessionStorage.removeItem(STORAGE_KEY); setStatusMessage("订单已取消，没有增加积分。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "取消订单失败"); }
    finally { setBusy(false); }
  };

  const reset = () => {
    setOrder(null); setBalance(null); setError(""); setStatusMessage(""); sessionStorage.removeItem(STORAGE_KEY);
    window.history.replaceState({}, "", "/recharge");
  };

  const minutes = String(Math.floor(remaining / 60)).padStart(2, "0");
  const seconds = String(remaining % 60).padStart(2, "0");
  const isExpired = order?.status === "expired" || (order?.status === "pending" && new Date(order.expires_at).getTime() <= Date.now());
  const isAlipay = order?.provider === "alipay";
  const modeLabel = order?.environment === "sandbox" ? "支付宝沙箱" : order?.environment === "production" ? "支付宝支付" : "本地模拟";

  return <main className="recharge-page"><div className="recharge-shell">
    <header className="recharge-header">
      <div className="recharge-header__bar"><a className="recharge-back" href="/dashboard">← 返回功能页</a><span className={`recharge-demo-tag ${order?.environment === "sandbox" ? "is-sandbox" : ""}`}><i aria-hidden="true" />{order ? modeLabel : "沙箱接入"}</span></div>
      <div className="recharge-heading"><div><span className="recharge-eyebrow">CREDIT TOP-UP</span><h1>积分充值</h1></div><p>支付宝沙箱用于接入测试，不会真实扣款；密钥未配置时自动保留本地模拟流程。</p></div>
    </header>
    <p className="recharge-sr-status" role="status" aria-live="polite" aria-atomic="true">{statusMessage}</p>

    {!order ? <div className="recharge-workspace" aria-busy={busy}>
      <section className="recharge-plan-panel" aria-labelledby="recharge-plan-title">
        <div className="recharge-section-heading"><span>01</span><div><h2 id="recharge-plan-title">选择充值方案</h2><p>金额和积分由服务端核算，支付订单 15 分钟内有效。</p></div></div>
        <div className="recharge-package-grid">{packages.map((item) => <button type="button" key={item.id} className={`recharge-package ${selection === item.id ? "is-selected" : ""}`} aria-pressed={selection === item.id} onClick={() => { setSelection(item.id); setError(""); }}><span className="recharge-package__top"><small>{item.name}</small>{item.badge && <em>{item.badge}</em>}</span><strong><span>¥</span>{item.amount.toLocaleString("zh-CN")}</strong><b>{item.points.toLocaleString("zh-CN")} 积分</b><span className="recharge-package__note">{item.note}</span><i aria-hidden="true" className="recharge-package__check"><SuccessIcon /></i></button>)}</div>
        <div className={`recharge-custom ${selection === "custom" ? "is-selected" : ""}`}>
          <button type="button" className="recharge-custom__selector" aria-pressed={selection === "custom"} onClick={() => { setSelection("custom"); setError(""); }}><span><small>自定义金额</small><b>按 1 元 = 10 积分计算</b></span><i aria-hidden="true"><SuccessIcon /></i></button>
          <label htmlFor="custom-recharge-amount">充值金额</label><div className="recharge-custom__input"><span>¥</span><input id="custom-recharge-amount" type="number" inputMode="numeric" min="1" max="5000" step="1" value={customAmount} aria-invalid={customHasError} aria-describedby="custom-amount-help" onFocus={() => setSelection("custom")} onChange={(event) => { setCustomAmount(event.target.value); setSelection("custom"); setError(""); }} /><b>{customPoints.toLocaleString("zh-CN")} 积分</b></div><small id="custom-amount-help">请输入 1–5000 元的整数</small>
        </div>
        {error && <p className="recharge-alert" role="alert">{error}</p>}
      </section>
      <aside className="recharge-summary" aria-label="订单预览"><span className="recharge-summary__label">订单预览</span><div className="recharge-summary__plan"><small>当前方案</small><strong>{preview.name}</strong></div><dl><div><dt>支付金额</dt><dd>¥{preview.amount.toLocaleString("zh-CN")}</dd></div><div><dt>预计到账</dt><dd>{preview.points.toLocaleString("zh-CN")} 积分</dd></div><div><dt>订单有效期</dt><dd>15 分钟</dd></div></dl><div className="recharge-summary__notice"><i aria-hidden="true" />优先创建支付宝沙箱订单；服务器未配置密钥时使用本地模拟。</div><button className="recharge-primary" type="button" onClick={createOrder} disabled={busy}>{busy ? "正在创建订单…" : "创建支付订单"}</button><small className="recharge-summary__footnote">沙箱和本地模拟均不会产生真实扣款。</small></aside>
    </div> : <section className={`payment-panel payment-panel--${order.status}`} aria-busy={busy}>
      {order.status === "succeeded" ? <div className="payment-result"><div className="payment-result__icon"><SuccessIcon /></div><span>{modeLabel}成功</span><h2>{order.points.toLocaleString("zh-CN")} 积分已到账</h2><p>当前余额：<strong>{balance === null ? "已更新" : `${balance.toLocaleString("zh-CN")} 积分`}</strong></p><div className="payment-order-meta"><span>订单号</span><code>{order.id}</code></div><div className="payment-actions"><a className="recharge-primary" href="/credits">查看积分记录</a><button type="button" onClick={reset}>继续充值</button></div></div>
      : order.status === "cancelled" || isExpired ? <div className="payment-result payment-result--muted"><span>{isExpired ? "订单已过期" : "订单已取消"}</span><h2>本次支付未完成</h2><p>{isExpired ? "15 分钟支付时限已结束，请重新创建订单。" : "订单已经关闭，没有增加积分。"}</p><button className="recharge-primary" type="button" onClick={reset}>重新选择方案</button></div>
      : <><div className="payment-panel__header"><div><span className={`payment-channel-label ${isAlipay ? "is-alipay" : ""}`}><i aria-hidden="true" />{modeLabel}</span><h2>{isAlipay ? "前往支付宝收银台" : "确认本地演示订单"}</h2><p>{isAlipay ? "付款完成后将返回本页，并由服务器验签确认到账。" : "当前未配置支付宝沙箱密钥，可手动完成演示订单。"}</p></div><div className="payment-timer"><span>剩余时间</span><strong role="timer" aria-label={`订单剩余 ${minutes} 分 ${seconds} 秒`}>{minutes}:{seconds}</strong></div></div>
        <div className="payment-panel__body">{isAlipay ? <div className="alipay-checkout" aria-label="支付宝沙箱支付"><div className="alipay-checkout__mark">支</div><strong>支付宝沙箱</strong><span>测试环境 · 不会真实扣款</span></div> : <div className="payment-qr-wrap"><div className="demo-qr" aria-label="不可扫描的演示二维码"><i>DEMO<small>不可扫码</small></i></div><p>本地演示二维码 · 不可扫码</p></div>}<div className="payment-detail"><span>本次支付</span><strong>¥{money(order.amount_cents)}</strong><p>到账 <b>{order.points.toLocaleString("zh-CN")}</b> 积分</p><dl><div><dt>充值方案</dt><dd>{order.package_name}</dd></div><div><dt>订单状态</dt><dd><span className="payment-status-dot" />等待支付确认</dd></div><div><dt>订单号</dt><dd><code>{order.id}</code></dd></div></dl></div></div>
        <div className="payment-notice"><strong>{isAlipay ? "以服务器验签结果为准" : "这是本地模拟支付"}</strong><span>{isAlipay ? "页面返回不会直接增加积分，只有支付宝异步通知或主动查询确认成功后才会入账。" : "手动确认只会写入本机 SQLite，不会向任何支付平台发送请求。"}</span></div>{error && <p className="recharge-alert" role="alert">{error}</p>}
        <div className="payment-actions"><button type="button" onClick={cancelOrder} disabled={busy}>取消订单</button>{isAlipay && <button type="button" onClick={syncOrder} disabled={busy}>{busy ? "正在查询…" : "刷新支付状态"}</button>}{isAlipay ? <a className="recharge-primary" href={order.checkout_url || "#"} aria-disabled={!order.checkout_url} onClick={(event) => { if (!order.checkout_url) event.preventDefault(); }}>前往支付宝沙箱收银台</a> : <button className="recharge-primary" type="button" onClick={completeMockOrder} disabled={busy || isExpired}>{busy ? "正在确认…" : "完成模拟支付"}</button>}</div>
      </>}
    </section>}
  </div></main>;
}
