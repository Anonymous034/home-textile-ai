"use client";

import { FormEvent, useEffect, useState } from "react";
import MaskedHeading from "./MaskedHeading";
import StickerTrail from "./StickerTrail";
import "./StickerTrail.css";
import SpecularButton from "./SpecularButton";
import "./SpecularButton.css";
import "./DemoLoginForm.css";

const VIDEO_SRC = "/hero-heading.mp4";
const POSTER_SRC = "/hero-heading-poster.jpg";
const API = process.env.NEXT_PUBLIC_STUDIO_API ?? "http://127.0.0.1:8000";

export default function HeroStage() {
  const [reduceMotion, setReduceMotion] = useState(false);
  const [backgroundFailed, setBackgroundFailed] = useState(false);
  const [showAccess, setShowAccess] = useState(false);
  const [personalKey, setPersonalKey] = useState("");
  const [checking, setChecking] = useState(false);
  const [accessError, setAccessError] = useState("");

  const useOwnerKey = () => {
    sessionStorage.removeItem("studio-personal-ark-key");
    sessionStorage.removeItem("studio-personal-plan-key");
    window.location.assign("/login");
  };

  const usePersonalKey = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecking(true);
    setAccessError("");
    try {
      const response = await fetch(`${API}/api/access/verify-user-key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: personalKey.trim() }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(typeof data.detail === "string" ? data.detail : "密钥验证未通过");
      sessionStorage.setItem("studio-personal-ark-key", personalKey.trim());
      sessionStorage.removeItem("studio-personal-plan-key");
      setPersonalKey("");
      window.location.assign("/dashboard");
    } catch (error) {
      setAccessError(error instanceof Error ? error.message : "暂时无法验证密钥");
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduceMotion(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return (
    <main className="hero-stage">
      <div className="hero-stage__ambient" aria-hidden="true">
        {!backgroundFailed && !reduceMotion ? (
          <video
            className="hero-stage__ambient-media"
            src={VIDEO_SRC}
            poster={POSTER_SRC}
            autoPlay
            muted
            loop
            playsInline
            preload="metadata"
            onError={() => setBackgroundFailed(true)}
          />
        ) : (
          <img
            className="hero-stage__ambient-media"
            src={POSTER_SRC}
            alt=""
          />
        )}
      </div>

      <div className="hero-stage__vignette" aria-hidden="true" />

      <div className="specular-button-wrap">
        <SpecularButton
          size="lg"
          radius={18}
          tint="#fafafa"
          tintOpacity={0}
          blur={0}
          textColor="#f5f5f5"
          lineColor="#f8f8f8"
          baseColor="#050505"
          intensity={1}
          shineSize={10}
          shineFade={40}
          thickness={1}
          speed={0.35}
          followMouse
          proximity={250}
          autoAnimate={false}
          onClick={() => setShowAccess(true)}
        >
          点击进入 →
        </SpecularButton>
      </div>

      {showAccess && <div className="hero-access-overlay" onClick={() => setShowAccess(false)}>
        <div className="login-aurora hero-access-aurora" aria-hidden="true">
          <i className="login-aurora__glow login-aurora__glow--cyan" />
          <i className="login-aurora__glow login-aurora__glow--blue" />
          <i className="login-aurora__glow login-aurora__glow--violet" />
          <i className="login-aurora__glow login-aurora__glow--center" />
        </div>
        <section className="hero-access-card" role="dialog" aria-modal="true" aria-labelledby="hero-access-title" onClick={(event) => event.stopPropagation()}>
          <span className="hero-access-card__glow" aria-hidden="true" />
          <button className="hero-access-close" type="button" aria-label="关闭" onClick={() => setShowAccess(false)}>×</button>
          <span className="hero-access-eyebrow">家纺AI视觉 · 接入选择</span>
          <h2 id="hero-access-title">选择 API Key 使用方式</h2>
          <p className="hero-access-intro">只需填写一个 API Key，后续功能会重复使用它。</p>
          <button className="hero-access-owner" type="button" onClick={useOwnerKey}>使用站点提供的 API Key <span>继续现有登录流程</span></button>
          <form onSubmit={usePersonalKey}>
            <div className="hero-access-field"><label htmlFor="personal-ark-key">你的 API Key</label>
              <input id="personal-ark-key" type="password" autoComplete="off" spellCheck={false} value={personalKey} onChange={(event) => setPersonalKey(event.target.value)} minLength={20} required placeholder="粘贴你的 API Key" /></div>
            <button type="submit" disabled={checking || personalKey.trim().length < 20}>{checking ? "正在验证…" : "验证并进入功能页"}</button>
            <p>密钥仅在当前浏览器标签页使用，不会覆盖站点配置；验证不会生成图片。</p>
            {accessError && <p className="hero-access-error" role="alert">{accessError}</p>}
          </form>
        </section>
      </div>}

      <StickerTrail>
        <section className="hero-stage__content" aria-labelledby="hero-title">
          <MaskedHeading
            id="hero-title"
            tag="h1"
            text="家纺AI视觉 全链路工作台"
            mediaType="video"
            src={VIDEO_SRC}
            poster={POSTER_SRC}
            fillScale={1.32}
            parallax={16}
            drift={9}
            brightness={1.48}
            saturation={1.32}
            reveal="rise"
            duration={1.25}
            stagger={0.13}
            trigger="view"
            textScale={0.073}
            weight={800}
            tracking={-0.045}
            lineHeight={1.02}
          />
        </section>
      </StickerTrail>
    </main>
  );
}
