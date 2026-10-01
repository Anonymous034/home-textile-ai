"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import "./DemoLoginForm.css";

const API = (process.env.NEXT_PUBLIC_STUDIO_API ?? "").replace(/\/+$/, "");
const HOME_PATH = "/";
const DEMO_LOGIN_HINT = "演示登录：手机号填 123，验证码填 123456；无需获取验证码或填写人机验证。";

const challenges = [
  { id: "subtract-17-1", label: "17 - 1 = ?" },
  { id: "add-8-4", label: "8 + 4 = ?" },
  { id: "subtract-9-3", label: "9 - 3 = ?" },
];

type DemoLoginFormProps = {
  onSuccess?: () => void;
  showBackLink?: boolean;
};

export default function DemoLoginForm({ onSuccess, showBackLink = true }: DemoLoginFormProps) {
  const cardRef = useRef<HTMLElement>(null);
  const [phone, setPhone] = useState("");
  const [humanAnswer, setHumanAnswer] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [challengeIndex, setChallengeIndex] = useState(0);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [requestingCode, setRequestingCode] = useState(false);
  const [codeRequested, setCodeRequested] = useState(false);
  const [countdown, setCountdown] = useState(0);

  useEffect(() => {
    const card = cardRef.current;
    if (!card) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const canHover = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    if (reduceMotion || !canHover) return;

    const context = gsap.context(() => {
      /* 这里是最常用的微调位置：上下 7 度，左右 9 度。 */
      const maxTiltX = 7;
      const maxTiltY = 9;
      const rotateXTo = gsap.quickTo(card, "rotationX", { duration: 0.24, ease: "power2.out" });
      const rotateYTo = gsap.quickTo(card, "rotationY", { duration: 0.24, ease: "power2.out" });
      const scaleTo = gsap.quickTo(card, "scale", { duration: 0.28, ease: "power2.out" });
      const spotXTo = gsap.quickTo(card, "--spot-x", { duration: 0.2, ease: "power2.out" });
      const spotYTo = gsap.quickTo(card, "--spot-y", { duration: 0.2, ease: "power2.out" });

      const onPointerMove = (event: PointerEvent) => {
        const bounds = card.getBoundingClientRect();
        const x = (event.clientX - bounds.left) / bounds.width;
        const y = (event.clientY - bounds.top) / bounds.height;

        rotateXTo((0.5 - y) * maxTiltX * 2);
        rotateYTo((x - 0.5) * maxTiltY * 2);
        scaleTo(1.012);
        spotXTo(x * 100);
        spotYTo(y * 100);
      };

      const resetCard = () => {
        rotateXTo(0);
        rotateYTo(0);
        scaleTo(1);
        spotXTo(50);
        spotYTo(35);
      };

      card.addEventListener("pointermove", onPointerMove);
      card.addEventListener("pointerleave", resetCard);

      return () => {
        card.removeEventListener("pointermove", onPointerMove);
        card.removeEventListener("pointerleave", resetCard);
      };
    }, card);

    return () => context.revert();
  }, []);

  const challenge = challenges[challengeIndex];

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = window.setInterval(() => setCountdown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [countdown]);

  const refreshChallenge = () => {
    setChallengeIndex((current) => (current + 1) % challenges.length);
    setHumanAnswer("");
    setMessage("");
  };

  const requestCode = async () => {
    if (!phone.trim()) {
      setMessage("请先输入手机号码");
      return;
    }
    if (phone.trim() === "123") {
      setMessage(DEMO_LOGIN_HINT);
      return;
    }
    setRequestingCode(true);
    setMessage("正在发送验证码…");
    try {
      const response = await fetch(`${API}/api/auth/request-code`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone,
          human_answer: humanAnswer,
          challenge_id: challenge.id,
        }),
      });
      const result = (await response.json()) as { ok?: boolean; message?: string; detail?: string; expires_in?: number };
      if (!response.ok || !result.ok) {
        setMessage(result.message || result.detail || "验证码发送失败，请稍后重试");
        return;
      }
      setCodeRequested(true);
      setCountdown(60);
      setMessage(`${result.message || "验证码已发送"}${result.expires_in ? `，${Math.floor(result.expires_in / 60)} 分钟内有效` : ""}`);
    } catch {
      setMessage("暂时无法连接验证服务，请稍后再试");
    } finally {
      setRequestingCode(false);
    }
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setMessage("正在验证填写的信息…");

    try {
      const demo = phone.trim() === "123";
      const response = await fetch(`${API}/api/auth/${demo ? "demo-login" : "verify-code"}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, code: verificationCode }),
      });
      const result = (await response.json()) as { ok: boolean; message?: string; detail?: string };

      if (!response.ok || !result.ok) {
        setMessage(result.message || result.detail || "验证没有通过，请检查后重试");
        return;
      }

      if (onSuccess) {
        onSuccess();
      } else {
        window.location.assign("/dashboard");
      }
    } catch {
      setMessage("暂时无法连接验证服务，请稍后再试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="demo-login" ref={cardRef} aria-labelledby="demo-login-title">
      <span className="demo-login__spotlight" aria-hidden="true" />
      {showBackLink && <a className="demo-login__back" href={HOME_PATH}>← 返回首页</a>}
      <div className="demo-login__heading">
        <p>家纺AI视觉</p>
        <h1 id="demo-login-title">登录 / 注册</h1>
        <span>使用手机号验证码安全登录；首次验证会自动创建账号。</span>
      </div>

      <div className="demo-login__mode" role="tablist" aria-label="登录方式">
        <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "is-active" : ""} onClick={() => setMode("login")}>登录</button>
        <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "is-active" : ""} onClick={() => setMode("register")}>注册</button>
      </div>

      <form onSubmit={submit}>
        <label className="demo-login__field">
          <span>手机号码</span>
          <input
            value={phone}
            onChange={(event) => { setPhone(event.target.value); setMessage(""); }}
            inputMode="numeric"
            autoComplete="tel"
            placeholder="例如 +86 138 0000 0000"
          />
        </label>

        <fieldset className="demo-login__group">
          <legend>人机验证</legend>
          <div className="demo-login__human-row">
            <div className="demo-login__question" aria-label={`题目：${challenge.label}`}>{challenge.label}</div>
            <input
              value={humanAnswer}
              onChange={(event) => setHumanAnswer(event.target.value)}
              inputMode="numeric"
              placeholder="请输入答案"
              aria-label="人机验证答案"
            />
            <button type="button" className="demo-login__refresh" onClick={refreshChallenge} aria-label="换一道题">
              ↻
            </button>
          </div>
        </fieldset>

        <fieldset className="demo-login__group">
          <legend>验证码</legend>
          <div className="demo-login__code-row">
            <input
              value={verificationCode}
              onChange={(event) => { setVerificationCode(event.target.value); setMessage(""); }}
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="6位验证码"
              aria-label="验证码"
            />
            <button type="button" onClick={requestCode} disabled={requestingCode || countdown > 0}>
              {requestingCode ? "发送中…" : countdown > 0 ? `${countdown}s 后重发` : codeRequested ? "重新获取" : "获取验证码"}
            </button>
          </div>
        </fieldset>

        <label className="demo-login__field">
          <span>邀请码（选填）</span>
          <input
            value={inviteCode}
            onChange={(event) => setInviteCode(event.target.value)}
            placeholder="填写邀请人邀请码可获得奖励"
          />
        </label>

        <p className="demo-login__message" aria-live="polite">{message || (phone.trim() === "" || phone.trim() === "123" ? DEMO_LOGIN_HINT : "验证码有效期 5 分钟。")}</p>
        <button className="demo-login__submit" type="submit" disabled={submitting}>
          {submitting ? "正在验证…" : mode === "register" ? "验证并注册" : "验证码登录"}
        </button>
      </form>
    </section>
  );
}
