import React from "react";
import { useCurrentFrame, useVideoConfig, interpolate } from "remotion";

const LINES: { text: string; delay: number; color: string }[] = [
  { text: "$ pip install aat-devqa",                              delay: 0,   color: "#cdd6f4" },
  { text: "  Collecting aat-devqa",                              delay: 28,  color: "#6272a4" },
  { text: "  Installing collected packages: aat-devqa",          delay: 50,  color: "#6272a4" },
  { text: "  ✔ Successfully installed aat-devqa-1.6.1",          delay: 72,  color: "#50fa7b" },
  { text: "",                                                     delay: 85,  color: "#cdd6f4" },
  { text: "$ aat init",                                           delay: 90,  color: "#cdd6f4" },
  { text: "  ✔ Created  .aat/config.yaml",                       delay: 115, color: "#50fa7b" },
  { text: "  ✔ Detected framework: Web (Playwright)",            delay: 130, color: "#50fa7b" },
  { text: "  ✔ AI provider: Claude (Anthropic)",                 delay: 145, color: "#50fa7b" },
  { text: "",                                                     delay: 157, color: "#cdd6f4" },
  { text: "$ aat run login.yaml",                                 delay: 162, color: "#cdd6f4" },
  { text: "  ▶ Loading scenario  login.yaml  (3 steps)",         delay: 185, color: "#8be9fd" },
  { text: "  ▶ Launching Playwright — Chromium",                 delay: 200, color: "#8be9fd" },
  { text: "  ✔ [1/3] navigate  →  /login         [PASS 0.4s]",  delay: 218, color: "#50fa7b" },
  { text: "  ✔ [2/3] fill_form →  credentials    [PASS 0.7s]",  delay: 234, color: "#50fa7b" },
  { text: "  ✔ [3/3] assert    →  dashboard url  [PASS 0.3s]",  delay: 250, color: "#50fa7b" },
  { text: "  ─────────────────────────────────────────────",     delay: 264, color: "#45475a" },
  { text: "  RESULT: 3/3 PASSED  •  Total: 1.4s",               delay: 270, color: "#50fa7b" },
];

function TypedLine({ text, startFrame, color }: { text: string; startFrame: number; color: string }) {
  const frame = useCurrentFrame();
  const elapsed = frame - startFrame;
  if (elapsed < 0) return <></>;
  if (text === "") return <div style={{ height: 10 }} />;
  const charsVisible = Math.floor(elapsed * 0.9);
  const done = charsVisible >= text.length;
  return (
    <div style={{ color, fontFamily: "Monaco, Menlo, monospace", fontSize: 14, lineHeight: 1.8 }}>
      {text.slice(0, charsVisible)}
      {!done && <span style={{ opacity: frame % 18 < 9 ? 1 : 0, color: "#f8f8f2" }}>█</span>}
    </div>
  );
}

export const TerminalScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 12],   [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [282, 300], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <div style={{ width, height, background: "#1e1e2e", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", opacity: fadeIn * fadeOut }}>
      {/* Scene label */}
      <div style={{ fontFamily: "Monaco, Menlo, monospace", fontSize: 12, color: "#6272a4", letterSpacing: 3, marginBottom: 18 }}>
        SCENE 1 — INSTALL &amp; RUN
      </div>

      {/* Terminal window */}
      <div style={{ width: 820, borderRadius: 12, overflow: "hidden", boxShadow: "0 30px 80px rgba(0,0,0,0.6)" }}>
        {/* Title bar */}
        <div style={{ background: "#313244", padding: "11px 16px", display: "flex", alignItems: "center", gap: 8 }}>
          {["#ff5f57","#febc2e","#28c840"].map((c) => (
            <div key={c} style={{ width: 12, height: 12, borderRadius: "50%", background: c }} />
          ))}
          <span style={{ color: "#a6adc8", fontFamily: "Monaco, Menlo, monospace", fontSize: 12, marginLeft: 14 }}>
            aat — bash — 820×420
          </span>
        </div>
        {/* Body */}
        <div style={{ background: "#1e1e2e", padding: "22px 26px", minHeight: 360 }}>
          {LINES.map((l, i) => (
            <TypedLine key={i} text={l.text} startFrame={l.delay} color={l.color} />
          ))}
        </div>
      </div>
    </div>
  );
};
