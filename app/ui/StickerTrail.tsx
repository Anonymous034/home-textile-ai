"use client";

import { useEffect, useRef, type HTMLAttributes } from "react";
import { gsap } from "gsap";
import "./StickerTrail.css";

const STICKER_TYPES = ["orb", "diamond", "bow", "pill", "flower", "bolt", "ring", "gem"];
const POOL_SIZE = 18;
const STEP_DISTANCE = 62;

export default function StickerTrail({ children, className = "", ...rest }: HTMLAttributes<HTMLDivElement>) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    const stickers = Array.from(root.querySelectorAll<HTMLElement>(".sticker-trail__item"));
    const context = gsap.context(() => {
      gsap.set(stickers, { autoAlpha: 0, xPercent: -50, yPercent: -50 });
    }, root);

    let poolIndex = 0;
    let previousX = 0;
    let previousY = 0;
    let hasPrevious = false;
    let bounds = root.getBoundingClientRect();
    const refreshBounds = () => { bounds = root.getBoundingClientRect(); };

    const showSticker = (x: number, y: number, directionX: number, directionY: number) => {
      const sticker = stickers[poolIndex % stickers.length];
      poolIndex += 1;
      gsap.killTweensOf(sticker);
      const angle = Math.atan2(directionY, directionX) * (180 / Math.PI);
      const startRotation = angle + gsap.utils.random(-42, 42);
      const scale = gsap.utils.random(0.78, 1.15);

      gsap.set(sticker, { x, y, xPercent: -50, yPercent: -50, rotation: startRotation, scale: 0.36, autoAlpha: 0 });
      gsap.timeline({ defaults: { overwrite: "auto" } })
        .to(sticker, { autoAlpha: 1, scale, duration: 0.2, ease: "back.out(2.2)" })
        .to(sticker, {
          y: y - gsap.utils.random(16, 34),
          rotation: startRotation + gsap.utils.random(-34, 34),
          scale: scale * 0.78,
          duration: 0.9,
          ease: "sine.out",
        }, "<0.08")
        .to(sticker, { autoAlpha: 0, scale: scale * 0.44, duration: 0.5, ease: "power2.in" }, "-=0.32");
    };

    const onPointerMove = (event: PointerEvent) => {
      const x = event.clientX - bounds.left;
      const y = event.clientY - bounds.top;
      if (!hasPrevious) {
        previousX = x;
        previousY = y;
        hasPrevious = true;
        showSticker(x, y, 1, 0);
        return;
      }

      const deltaX = x - previousX;
      const deltaY = y - previousY;
      const distance = Math.hypot(deltaX, deltaY);
      if (distance < STEP_DISTANCE) return;
      const amount = Math.min(4, Math.floor(distance / STEP_DISTANCE));
      for (let index = 1; index <= amount; index += 1) {
        const progress = index / amount;
        showSticker(previousX + deltaX * progress, previousY + deltaY * progress, deltaX, deltaY);
      }
      previousX = x;
      previousY = y;
    };

    const onPointerLeave = () => { hasPrevious = false; };
    root.addEventListener("pointermove", onPointerMove, { passive: true });
    root.addEventListener("pointerleave", onPointerLeave);
    window.addEventListener("resize", refreshBounds, { passive: true });

    return () => {
      root.removeEventListener("pointermove", onPointerMove);
      root.removeEventListener("pointerleave", onPointerLeave);
      window.removeEventListener("resize", refreshBounds);
      gsap.killTweensOf(stickers);
      context.revert();
    };
  }, []);

  return (
    <div ref={rootRef} className={`sticker-trail ${className}`.trim()} {...rest}>
      <div className="sticker-trail__layer" aria-hidden="true">
        {Array.from({ length: POOL_SIZE }, (_, index) => (
          <span className={`sticker-trail__item sticker--${STICKER_TYPES[index % STICKER_TYPES.length]}`} key={index}>
            <i className="sticker-trail__art" />
          </span>
        ))}
      </div>
      <div className="sticker-trail__content">{children}</div>
    </div>
  );
}
