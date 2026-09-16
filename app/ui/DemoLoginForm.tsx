"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import "./DemoLoginForm.css";

const challenges = [
  { id: "subtract-17-1", label: "17 - 1 = ?" },
  { id: "add-8-4", label: "8 + 4 = ?" },
  { id: "subtract-9-3", label: "9 - 3 = ?" },
];

export default function DemoLoginForm() {
  const cardRef = useRef<HTMLElement>(null);
  const [phone, setPhone] = useState("");
  const [humanAnswer, setHumanAnswer] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [challengeIndex, setChallengeIndex] = useState(0);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

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

  const refreshChallenge = () => {
    setChallengeIndex((current) => (current + 1) % challenges.length);
    setHumanAnswer("");
    setMessage("");
  };

  const showDemoCode = () => {
    setMessage(phone.trim() === "123" ? "演示验证码：123456" : "请先输入演示手机号 123");
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setMessage("正在验证填写的信息…");

    try {
      const response = await fetch("/api/demo-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone,
          humanAnswer,
          verificationCode,
          inviteCode,
          challengeId: challenge.id,
        }),
      });
      const result = (await response.json()) as { ok: boolean; message?: string };

      if (!response.ok || !result.ok) {
        setMessage(result.message || "验证没有通过，请检查后重试");
        return;
      }

      window.location.assign("/dashboard");
    } catch {
      setMessage("暂时无法连接验证服务，请稍后再试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="demo-login" ref={cardRef} aria-labelledby="demo-login-title">
      <span className="demo-login__spotlight" aria-hidden="true" />
      <a className="demo-login__back" href="/">← 返回首页</a>
      <div className="demo-login__heading">
        <p>家纺AI视觉</p>
        <h1 id="demo-login-title">登录 / 注册</h1>
        <span>这是演示页面，请使用下方提示的信息登录。</span>
      </div>

      <form onSubmit={submit}>
        <label className="demo-login__field">
          <span>手机号码</span>
          <input
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            inputMode="numeric"
            autoComplete="tel"
            placeholder="演示手机号：123"
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
              onChange={(event) => setVerificationCode(event.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="6位验证码"
              aria-label="验证码"
            />
            <button type="button" onClick={showDemoCode}>获取验证码</button>
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

        <p className="demo-login__message" aria-live="polite">{message || "演示账号：123　验证码：123456"}</p>
        <button className="demo-login__submit" type="submit" disabled={submitting}>
          {submitting ? "正在登录…" : "登录 / 注册"}
        </button>
      </form>
    </section>
  );
}
