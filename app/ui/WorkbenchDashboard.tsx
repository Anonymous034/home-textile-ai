"use client";

import { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import UserMenu from "./UserMenu";
import "./UserMenu.css";
import "./WorkbenchDashboard.css";

const demoUser = {
  userId: "demo-user-123",
  displayName: "演示用户",
  email: "123",
  fullName: "演示用户",
};

const galleryItems = [
  { id: "studio", href: "/studio", title: "AI 虚拟影棚", image: "/bento-gallery/ai-studio.png", ratio: "490 / 413" },
  { id: "replicate", href: "/replicate", title: "爆款复刻", image: "/bento-gallery/bestseller-v2.png", ratio: "1367 / 1151" },
  { id: "detail-page", href: "/detail-page", title: "详情页制作", image: "/bento-gallery/detail-page.png", ratio: "498 / 405" },
  { id: "template", href: "/template", title: "使用模板", image: "/bento-gallery/template.png", ratio: "490 / 417" },
  { id: "pattern", href: "/pattern", title: "花型创作", image: "/bento-gallery/pattern.png", ratio: "492 / 413" },
  { id: "video", href: "/video", title: "爆款视频", image: "/bento-gallery/video.png", ratio: "490 / 413" },
  { id: "sketch", href: "/sketch", title: "画稿生图", image: "/bento-gallery/sketch.png", ratio: "492 / 413" },
  { id: "local-edit", href: "/local-edit", title: "局部编辑", image: "/bento-gallery/local-edit.png", ratio: "492 / 413" },
  { id: "buyer-show", href: "/buyer-show", title: "买家秀", image: "/bento-gallery/buyer-show.png", ratio: "492 / 413" },
  { id: "upscale", href: "/upscale", title: "一键高清", image: "/bento-gallery/hd.png", ratio: "492 / 413" },
];

function wrappedOffset(index: number, activeIndex: number, total: number) {
  let offset = (index - activeIndex + total) % total;
  if (offset > total / 2) offset -= total;
  return offset;
}

export default function WorkbenchDashboard() {
  const rootRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLElement>(null);
  const deckRef = useRef<HTMLDivElement>(null);
  const changeSlideRef = useRef<(step: number) => void>(() => undefined);
  const selectSlideRef = useRef<(index: number) => void>(() => undefined);
  const pointerStartRef = useRef<number | null>(null);
  const draggedRef = useRef(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [menuUser, setMenuUser] = useState(demoUser);

  useEffect(() => {
    if (sessionStorage.getItem("studio-personal-ark-key")) {
      setMenuUser({ userId: "personal-key", displayName: "个人密钥用户", email: "个人密钥", fullName: "个人密钥用户" });
    }
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    const stage = stageRef.current;
    const deck = deckRef.current;
    if (!root || !stage || !deck) return;

    const requestedTool = new URLSearchParams(window.location.search).get("tool");
    let currentIndex = Math.max(0, galleryItems.findIndex((item) => item.id === requestedTool));
    let transition: gsap.core.Timeline | null = null;
    let resizeTimer = 0;
    let wheelReady = true;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const context = gsap.context(() => {
      const cards = gsap.utils.toArray<HTMLElement>(".infinite-card", deck);

      const cardState = (offset: number) => {
        const distance = Math.abs(offset);
        const stageWidth = stage.clientWidth;
        const mobile = stageWidth < 700;
        const step = mobile ? Math.min(stageWidth * 0.32, 150) : Math.min(stageWidth * 0.225, 270);
        const scales = mobile
          ? [1, 0.66, 0.44, 0.3, 0.2, 0.14]
          : [1, 0.72, 0.51, 0.36, 0.25, 0.17];
        const alphas = [1, 0.72, 0.42, 0.22, 0.1, 0];

        return {
          x: offset * step,
          y: distance * (mobile ? 9 : 15),
          xPercent: -50,
          yPercent: -50,
          scale: scales[Math.min(distance, scales.length - 1)],
          rotationY: offset * (mobile ? -3 : -5),
          autoAlpha: alphas[Math.min(distance, alphas.length - 1)],
          zIndex: 30 - distance,
          pointerEvents: distance <= 2 ? "auto" : "none",
        };
      };

      const draw = (animate: boolean) => {
        transition?.kill();
        transition = gsap.timeline({
          defaults: {
            duration: animate && !reduceMotion ? 0.72 : 0,
            ease: "power3.inOut",
            overwrite: "auto",
          },
        });

        cards.forEach((card, index) => {
          const nextOffset = wrappedOffset(index, currentIndex, cards.length);
          const previousOffset = Number(card.dataset.offset ?? nextOffset);

          if (animate && Math.abs(nextOffset - previousOffset) > 1) {
            const entrySide = nextOffset < 0 ? -1 : 1;
            gsap.set(card, cardState(entrySide * (Math.floor(cards.length / 2) + 1)));
          }

          card.dataset.offset = String(nextOffset);
          transition?.to(card, cardState(nextOffset), 0);
        });
      };

      const updateIndex = (nextIndex: number) => {
        currentIndex = (nextIndex + cards.length) % cards.length;
        setActiveIndex(currentIndex);
        draw(true);
      };

      changeSlideRef.current = (step) => updateIndex(currentIndex + step);
      selectSlideRef.current = (index) => updateIndex(index);

      setActiveIndex(currentIndex);
      draw(false);
    }, root);

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") changeSlideRef.current(-1);
      if (event.key === "ArrowRight") changeSlideRef.current(1);
    };

    const onWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaY) < 16 || !wheelReady) return;
      event.preventDefault();
      wheelReady = false;
      changeSlideRef.current(event.deltaY > 0 ? 1 : -1);
      window.setTimeout(() => { wheelReady = true; }, 520);
    };

    const onResize = () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => selectSlideRef.current(currentIndex), 160);
    };

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onResize);
    stage.addEventListener("wheel", onWheel, { passive: false });

    return () => {
      transition?.kill();
      changeSlideRef.current = () => undefined;
      selectSlideRef.current = () => undefined;
      window.clearTimeout(resizeTimer);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onResize);
      stage.removeEventListener("wheel", onWheel);
      context.revert();
    };
  }, []);

  const finishDrag = (clientX: number) => {
    const startX = pointerStartRef.current;
    pointerStartRef.current = null;
    if (startX === null) return false;
    const distance = clientX - startX;
    if (Math.abs(distance) > 42) {
      draggedRef.current = true;
      changeSlideRef.current(distance > 0 ? -1 : 1);
      return true;
    }
    return false;
  };

  return (
    <main className="workbench" ref={rootRef}>
      <header className="workbench__topbar">
        <a className="workbench__brand" href="/dashboard" aria-label="返回强视觉ai生图工作台">
          <span aria-hidden="true">
            <img src="/brand-logo.jpg" alt="" />
          </span>
          <strong>强视觉ai生图</strong>
        </a>
        <div className="workbench__topbar-center" aria-live="polite">
          {galleryItems[activeIndex].title}
        </div>
        <UserMenu user={menuUser} logoutHref="/" />
      </header>

      <section
        className="infinite-slider"
        ref={stageRef}
        aria-label="家具AI创作工具轮播"
      >
        <div className="infinite-slider__hint" aria-hidden="true">
          <span>10 项创作工具</span>
          <i />
          <span>拖动、滚轮或方向键切换</span>
        </div>

        <div
          className="infinite-slider__deck"
          ref={deckRef}
          onPointerDown={(event) => {
            pointerStartRef.current = event.clientX;
            draggedRef.current = false;
          }}
          onPointerUp={(event) => {
            const featureLink = (event.target as HTMLElement).closest<HTMLAnchorElement>('a[data-feature-link="true"]');
            const wasDragged = finishDrag(event.clientX);
            if (featureLink && !wasDragged && Number(featureLink.dataset.index) === activeIndex) {
              event.preventDefault();
              window.location.assign(featureLink.href);
            }
          }}
          onPointerCancel={() => { pointerStartRef.current = null; }}
        >
          {galleryItems.map((item, index) => {
            const cardImage = <img src={item.image} alt={`${item.title}功能卡片`} draggable={false} />;

            const featureHref = item.href;

            if (featureHref) {
              return (
                <a
                  className="infinite-card"
                  style={{ aspectRatio: item.ratio }}
                  href={featureHref}
                  data-feature-link="true"
                  data-index={index}
                  onClick={(event) => {
                    if (draggedRef.current) {
                      draggedRef.current = false;
                      event.preventDefault();
                      return;
                    }
                    if (index !== activeIndex) {
                      event.preventDefault();
                      selectSlideRef.current(index);
                    }
                  }}
                  aria-label={index === activeIndex ? `进入${item.title}` : `查看${item.title}`}
                  aria-current={index === activeIndex ? "true" : undefined}
                  tabIndex={index === activeIndex ? 0 : -1}
                  key={item.title}
                >
                  {cardImage}
                </a>
              );
            }

            return (
              <button
                className="infinite-card"
                style={{ aspectRatio: item.ratio }}
                type="button"
                onClick={() => {
                  if (draggedRef.current) {
                    draggedRef.current = false;
                    return;
                  }
                  selectSlideRef.current(index);
                }}
                aria-label={`查看${item.title}`}
                aria-current={index === activeIndex ? "true" : undefined}
                tabIndex={index === activeIndex ? 0 : -1}
                key={item.title}
              >
                {cardImage}
              </button>
            );
          })}
        </div>

        <div className="infinite-slider__controls">
          <button type="button" onClick={() => changeSlideRef.current(-1)} aria-label="上一张功能卡片">
            上一个
          </button>
          <span aria-live="polite">{String(activeIndex + 1).padStart(2, "0")} / {galleryItems.length}</span>
          <button type="button" onClick={() => changeSlideRef.current(1)} aria-label="下一张功能卡片">
            下一个
          </button>
        </div>
      </section>
    </main>
  );
}
