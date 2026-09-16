"use client";

import { useEffect, useRef, type ButtonHTMLAttributes, type CSSProperties, type ReactNode } from "react";
import "./SpecularButton.css";

type SpecularButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & {
  children: ReactNode;
  size?: "sm" | "md" | "lg";
  radius?: number;
  tint?: string;
  tintOpacity?: number;
  blur?: number;
  textColor?: string;
  lineColor?: string;
  baseColor?: string;
  intensity?: number;
  shineSize?: number;
  shineFade?: number;
  thickness?: number;
  speed?: number;
  followMouse?: boolean;
  proximity?: number;
  autoAnimate?: boolean;
};

type SpecularStyle = CSSProperties & Record<`--${string}`, string | number>;

export default function SpecularButton({
  children,
  size = "md",
  radius = 18,
  tint = "#fafafa",
  tintOpacity = 0,
  blur = 0,
  textColor = "#f5f5f5",
  lineColor = "#f8f8f8",
  baseColor = "#487f7d",
  intensity = 1,
  shineSize = 10,
  shineFade = 40,
  thickness = 1,
  speed = 0.35,
  followMouse = false,
  proximity = 250,
  autoAnimate = false,
  className = "",
  ...rest
}: SpecularButtonProps) {
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const button = buttonRef.current;
    if (!button || !followMouse) return;

    const onMove = (event: PointerEvent) => {
      const rect = button.getBoundingClientRect();
      const localX = event.clientX - rect.left;
      const localY = event.clientY - rect.top;
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const distance = Math.hypot(event.clientX - centerX, event.clientY - centerY);
      const strength = Math.max(0, 1 - distance / proximity);
      const angle = Math.atan2(event.clientY - centerY, event.clientX - centerX) * (180 / Math.PI) + 90;

      button.style.setProperty("--pointer-x", `${localX}px`);
      button.style.setProperty("--pointer-y", `${localY}px`);
      button.style.setProperty("--pointer-angle", `${angle}deg`);
      button.style.setProperty("--pointer-strength", strength.toFixed(3));
    };

    const reset = () => button.style.setProperty("--pointer-strength", "0");
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("blur", reset);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("blur", reset);
    };
  }, [followMouse, proximity]);

  return (
    <button
      ref={buttonRef}
      type="button"
      className={`specular-button specular-button--${size} ${autoAnimate ? "is-auto" : ""} ${className}`.trim()}
      style={{
        "--spec-radius": `${radius}px`,
        "--spec-tint": tint,
        "--spec-tint-opacity": tintOpacity,
        "--spec-blur": `${blur}px`,
        "--spec-text": textColor,
        "--spec-line": lineColor,
        "--spec-base": baseColor,
        "--spec-intensity": intensity,
        "--spec-shine-size": `${shineSize}%`,
        "--spec-shine-fade": `${shineFade}%`,
        "--spec-thickness": `${thickness}px`,
        "--spec-speed": `${speed}s`,
        "--pointer-x": "50%",
        "--pointer-y": "50%",
        "--pointer-angle": "90deg",
        "--pointer-strength": autoAnimate ? 0.7 : 0,
      } as SpecularStyle}
      {...rest}
    >
      <span className="specular-button__surface" aria-hidden="true" />
      <span className="specular-button__label">{children}</span>
    </button>
  );
}
