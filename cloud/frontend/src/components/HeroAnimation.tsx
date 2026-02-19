"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";

/* ------------------------------------------------------------------ */
/* Scene durations (ms)                                                */
/* ------------------------------------------------------------------ */
const SCENE_DURATIONS = [3000, 2000, 3000, 2000, 2000, 3000, 2000]; // 17s total
const FULL_URL = "https://mysite.com";

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export default function HeroAnimation() {
  const t = useTranslations("landing");
  const [scene, setScene] = useState(0);
  const [typedUrl, setTypedUrl] = useState("");
  const [progress, setProgress] = useState(0);
  const [visibleCards, setVisibleCards] = useState(0);

  // Scene auto-advance
  useEffect(() => {
    const timer = setTimeout(() => {
      setScene((s) => (s + 1) % 7);
    }, SCENE_DURATIONS[scene]);
    return () => clearTimeout(timer);
  }, [scene]);

  // Scene 0: typing effect
  useEffect(() => {
    if (scene !== 0) return;
    setTypedUrl("");
    let i = 0;
    const iv = setInterval(() => {
      i++;
      setTypedUrl(FULL_URL.slice(0, i));
      if (i >= FULL_URL.length) clearInterval(iv);
    }, 120);
    return () => clearInterval(iv);
  }, [scene]);

  // Scene 2: cards slide-in one by one
  useEffect(() => {
    if (scene !== 2) { setVisibleCards(0); return; }
    setVisibleCards(0);
    const t1 = setTimeout(() => setVisibleCards(1), 400);
    const t2 = setTimeout(() => setVisibleCards(2), 1200);
    const t3 = setTimeout(() => setVisibleCards(3), 2000);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
  }, [scene]);

  // Scene 3: progress bar
  useEffect(() => {
    if (scene !== 3) { setProgress(0); return; }
    setProgress(0);
    const iv = setInterval(() => {
      setProgress((p) => {
        if (p >= 100) { clearInterval(iv); return 100; }
        return p + 5;
      });
    }, 80);
    return () => clearInterval(iv);
  }, [scene]);

  const renderScene = useCallback(() => {
    switch (scene) {
      /* Scene 0 — Typing URL */
      case 0:
        return (
          <div className="flex flex-col items-center justify-center h-full gap-4">
            <div className="text-lg font-bold text-blue-400">AWT Cloud</div>
            <p className="text-xs text-gray-400">{t("animSubtitle")}</p>
          </div>
        );

      /* Scene 1 — Generate Scenarios button */
      case 1:
        return (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <div className="w-full max-w-xs rounded-lg bg-gray-800 border border-gray-600 px-3 py-2 text-xs text-gray-300 font-mono">
              {FULL_URL}
            </div>
            <button className="rounded-lg bg-blue-500 px-4 py-2 text-xs font-medium text-white animate-hero-pulse shadow-lg shadow-blue-500/30">
              {t("animGenerate")}
            </button>
          </div>
        );

      /* Scene 2 — Scenario cards */
      case 2:
        return (
          <div className="flex flex-col gap-2 justify-center h-full px-2">
            {[
              { icon: "\ud83c\udf10", text: t("animCard1") },
              { icon: "\ud83d\udc46", text: t("animCard2") },
              { icon: "\u2705", text: t("animCard3") },
            ].map((card, i) => (
              <div
                key={i}
                className={`flex items-center gap-2 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-xs transition-all duration-500 ${
                  i < visibleCards
                    ? "opacity-100 translate-x-0"
                    : "opacity-0 translate-x-8"
                }`}
              >
                <span>{card.icon}</span>
                <span className="text-gray-300">{card.text}</span>
              </div>
            ))}
          </div>
        );

      /* Scene 3 — Run Test + progress */
      case 3:
        return (
          <div className="flex flex-col items-center justify-center h-full gap-4">
            <button className="rounded-lg bg-green-500 px-4 py-2 text-xs font-medium text-white">
              {t("animRunTest")}
            </button>
            <div className="w-full max-w-xs">
              <div className="h-2 rounded-full bg-gray-700 overflow-hidden">
                <div
                  className="h-full rounded-full bg-blue-500 transition-all duration-100"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="mt-1 text-center text-[10px] text-gray-500">
                {t("animRunning")} {progress}%
              </p>
            </div>
          </div>
        );

      /* Scene 4 — Results: 2 passed, 1 failed */
      case 4:
        return (
          <div className="flex flex-col gap-2 justify-center h-full px-4">
            <div className="flex items-center gap-2 text-xs">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-green-900/50 text-green-400 text-[10px]">{"\u2713"}</span>
              <span className="text-green-400">{t("animHomepage")}</span>
              <span className="ml-auto text-green-500 font-medium">{t("animPassed")}</span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-green-900/50 text-green-400 text-[10px]">{"\u2713"}</span>
              <span className="text-green-400">{t("animDashboard")}</span>
              <span className="ml-auto text-green-500 font-medium">{t("animPassed")}</span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-red-900/50 text-red-400 text-[10px]">{"\u2717"}</span>
              <span className="text-red-400">{t("animLogin")}</span>
              <span className="ml-auto text-red-500 font-medium">{t("animFailed")}</span>
            </div>
            <div className="mt-2 text-center text-xs text-gray-500">
              {t("animResult")}
            </div>
          </div>
        );

      /* Scene 5 — AI analysis + PR creation */
      case 5:
        return (
          <div className="flex flex-col items-center justify-center h-full gap-3 px-4">
            <div className="flex items-center gap-2 text-xs text-yellow-400">
              <span className="inline-block h-3 w-3 rounded-full border-2 border-yellow-400 border-t-transparent animate-spin" />
              {t("animAnalyzing")}
            </div>
            <div className="w-full rounded-lg border border-gray-700 bg-gray-800 p-3 animate-hero-fadein">
              <div className="flex items-center gap-2 text-xs">
                <span className="text-purple-400">{"\ud83d\udd00"}</span>
                <span className="text-gray-300 font-medium">{t("animPrTitle")}</span>
              </div>
              <div className="mt-2 flex items-center gap-1 text-[10px] text-gray-500">
                <span className="rounded bg-purple-900/50 px-1.5 py-0.5 text-purple-400">PR #42</span>
                <span>main {"\u2190"} fix/login-selector</span>
              </div>
            </div>
            <div className="flex items-center gap-1 text-xs text-green-400 animate-hero-fadein-delay">
              <span>{"\u2705"}</span> {t("animPrCreated")}
            </div>
          </div>
        );

      /* Scene 6 — All green */
      case 6:
        return (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <div className="text-2xl animate-hero-bounce">{"\ud83c\udf89"}</div>
            <div className="flex flex-col gap-1">
              {[t("animHomepage"), t("animLogin"), t("animDashboard")].map((label, i) => (
                <div key={i} className="flex items-center gap-2 text-xs text-green-400">
                  <span>{"\u2705"}</span> {label}
                </div>
              ))}
            </div>
            <div className="rounded-full bg-green-900/50 px-3 py-1 text-xs font-bold text-green-400 animate-hero-pulse">
              {t("animAllPassed")}
            </div>
          </div>
        );

      default:
        return null;
    }
  }, [scene, typedUrl, progress, visibleCards, t]);

  return (
    <div className="relative mx-auto w-full max-w-lg">
      {/* Fake browser chrome */}
      <div className="overflow-hidden rounded-xl border border-gray-700/50 bg-gray-900 shadow-2xl shadow-blue-900/20">
        {/* Title bar */}
        <div className="flex items-center gap-2 border-b border-gray-700/50 bg-gray-800/80 px-4 py-2.5">
          <div className="flex gap-1.5">
            <div className="h-3 w-3 rounded-full bg-red-500/80" />
            <div className="h-3 w-3 rounded-full bg-yellow-500/80" />
            <div className="h-3 w-3 rounded-full bg-green-500/80" />
          </div>
          <div className="ml-3 flex-1 rounded-md bg-gray-700/50 px-3 py-1.5 text-xs text-gray-400 font-mono">
            {scene === 0 ? (
              <>
                {typedUrl}
                <span className="animate-blink">|</span>
              </>
            ) : (
              FULL_URL
            )}
          </div>
        </div>

        {/* Content area */}
        <div className="relative h-64 p-4">{renderScene()}</div>
      </div>

      {/* Scene indicator dots */}
      <div className="mt-3 flex justify-center gap-1.5">
        {SCENE_DURATIONS.map((_, i) => (
          <div
            key={i}
            className={`h-1.5 rounded-full transition-all duration-300 ${
              i === scene ? "w-4 bg-blue-500" : "w-1.5 bg-gray-300"
            }`}
          />
        ))}
      </div>
    </div>
  );
}
