"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatGPTUser } from "../chatgpt-auth";

const API = "";

type UserMenuProps = {
  user: ChatGPTUser | null;
  avatarUrl?: string | null;
  logoutHref?: string;
  onLoginRequest?: () => void;
};

const menuItems = [
  { icon: "▰", label: "我的作品", href: "/my-works" },
  { icon: "▱", label: "积分中心", href: "/credits" },
  { icon: "¥", label: "积分充值", href: "/recharge", accent: true },
  { icon: "⚙", label: "个人设置", href: "/settings" },
  { icon: "▤", label: "发票管理" },
  { icon: "▣", label: "登录管理" },
  { icon: "♕", label: "会员优惠", accent: true },
];

export default function UserMenu({ user, avatarUrl, logoutHref = "/signout-with-chatgpt?return_to=%2F", onLoginRequest }: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const [watermark, setWatermark] = useState(true);
  const rootRef = useRef<HTMLDivElement>(null);
  const initial = (user?.displayName || user?.email || "我").trim().charAt(0).toUpperCase();

  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  return (
    <div className="user-menu" ref={rootRef}>
      <button
        className="user-menu__trigger"
        type="button"
        aria-label={user ? "打开个人中心" : "打开登录菜单"}
        aria-expanded={open}
        aria-controls="user-menu-panel"
        onClick={() => setOpen((value) => !value)}
      >
        {avatarUrl ? <img src={avatarUrl} alt="个人头像" /> : <span>{initial}</span>}
        <i aria-hidden="true" className={open ? "is-open" : ""} />
      </button>

      {open && (
        <div className={`user-menu__panel ${user ? "is-signed-in" : "is-guest"}`} id="user-menu-panel">
          {user ? (
            <>
              <div className="user-menu__account">
                <div className="user-menu__account-avatar">
                  {avatarUrl ? <img src={avatarUrl} alt="" /> : <span>{initial}</span>}
                </div>
                <div>
                  <small>账号</small>
                  <strong>{user.email || user.userId}</strong>
                </div>
              </div>

              <div className="user-menu__links">
                {menuItems.map((item) => item.href ? (
                  <a className={item.accent ? "is-accent" : ""} href={item.href} key={item.label}>
                    <span aria-hidden="true">{item.icon}</span>{item.label}
                  </a>
                ) : (
                  <button className={item.accent ? "is-accent" : ""} type="button" key={item.label}>
                    <span aria-hidden="true">{item.icon}</span>{item.label}
                  </button>
                ))}
                <button type="button" onClick={() => setWatermark((value) => !value)}>
                  <span aria-hidden="true">▥</span>
                  生成水印
                  <i className={`user-menu__switch ${watermark ? "is-on" : ""}`} aria-label={watermark ? "水印已开启" : "水印已关闭"} />
                </button>
              </div>

              <a className="user-menu__logout" href={logoutHref} onClick={(event) => {
                event.preventDefault();
                sessionStorage.removeItem("studio-personal-ark-key");
                sessionStorage.removeItem("studio-personal-plan-key");
                fetch(`${API}/api/auth/logout`, { method: "POST", credentials: "include" })
                  .catch(() => undefined)
                  .finally(() => window.location.assign(logoutHref));
              }}>
                <span aria-hidden="true">↪</span>
                退出登录
              </a>
            </>
          ) : (
            <a className="user-menu__login" href="/login" onClick={(event) => {
              if (!onLoginRequest) return;
              event.preventDefault();
              setOpen(false);
              onLoginRequest();
            }}>登录 / 注册</a>
          )}
        </div>
      )}
    </div>
  );
}
