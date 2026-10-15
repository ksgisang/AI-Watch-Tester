import React from "react";
import { useCurrentFrame, useVideoConfig, interpolate, spring } from "remotion";

const STEPS = [
  {
    icon: "❌",
    label: "Test failed",
    sub: "Step 2/3 — assertion mismatch on /dashboard",
    detail: "Expected URL to contain '/dashboard'\nReceived  '/login?error=invalid_credentials'",
    color: "#ff5555",
    frame: 15,
  },
  {
    icon: "🤖",
    label: "AI analyzing...",
    sub: "Claude reviewing screenshot diff + error trace",
    detail: "Comparing expected vs actual DOM snapshot\nIdentifying root cause: wrong password selector",
    color: "#8be9fd",
    frame: 75,
  },
  {
    icon: "🔧",
    label: "AI fixing scenario",
    sub: "Patching login.yaml — selector updated",
    detail: "- selector: '#password'\n+ selector: 'input[name=\"user_password\"]'",
    color: "#ffb86c",
    frame: 148,
  },
  {
    icon: "✅",
    label: "Test passed!",
    sub: "Retry #2 — all 3 steps green",
    detail: "[1/3] navigate    /login          PASS 0.4s\n[2/3] fill_form  credentials    PASS 0.8s\n[3/3] assert     /dashboard url  PASS 0.3s",
    color: "#50fa7b",
    frame: 218,
  },
];

function StepCard({ icon, label, sub, detail, color, startFrame }: {
  icon: string; label: string; sub: string; detail: string; color: string; startFrame: number;
}) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const sc = spring({ fps, frame: frame - startFrame, config: { damping: 20, stiffness: 150 } });
  const op = interpolate(frame, [startFrame, startFrame + 12], [0, 1], { extrapolateRight: "clamp", extrapolateLeft: "clamp" });
  const detailOp = interpolate(frame, [startFrame + 15, startFrame + 30], [0, 1], { extrapolateRight: "clamp", extrapolateLeft: "clamp" });

  if (frame < startFrame) return null;

  return (
    <div style={{
      transform: `scale(${sc})`, opacity: op,
      background: "#313244",
      border: `2px solid ${color}`,
      borderRadius: 14,
      padding: "16px 24px",
      display: "flex",
      gap: 18,
      boxShadow: `0 0 24px ${color}2a`,
      marginBottom: 12,
      width: 700,
    }}>
      <span style={{ fontSize: 34, lineHeight: 1 }}>{icon}</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontFamily: "Monaco, Menlo, monospace", fontSize: 18, color, fontWeight: "bold" }}>{label}</div>
        <div style={{ fontFamily: "Monaco, Menlo, monospace", fontSize: 12, color: "#a6adc8", marginTop: 3 }}>{sub}</div>
        <div style={{ opacity: detailOp, marginTop: 8, background: "#1e1e2e", borderRadius: 6, padding: "8px 12px" }}>
          {detail.split("\n").map((line, i) => (
            <div key={i} style={{ fontFamily: "Monaco, Menlo, monospace", fontSize: 11, color: "#6272a4", lineHeight: 1.7 }}>
              {line}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ProgressBar({ startFrame, endFrame, color }: { startFrame: number; endFrame: number; color: string }) {
  const frame = useCurrentFrame();
  if (frame < startFrame) return null;
  const p = interpolate(frame, [startFrame, endFrame], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ width: 700, height: 3, background: "#45475a", borderRadius: 2, marginBottom: 10, overflow: "hidden" }}>
      <div style={{ width: `${p * 100}%`, height: "100%", background: color, borderRadius: 2 }} />
    </div>
  );
}

export const DevQAScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 15],   [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [282, 300], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  const headerOp = interpolate(frame, [5, 20], [0, 1], { extrapolateRight: "clamp" });

  const attemptLabel = frame >= 148 ? "Attempt #2" : "Attempt #1";

  return (
    <div style={{ width, height, background: "#1e1e2e", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", opacity: fadeIn * fadeOut }}>
      {/* Header */}
      <div style={{ opacity: headerOp, marginBottom: 24, textAlign: "center" }}>
        <div style={{ fontFamily: "Monaco, Menlo, monospace", fontSize: 11, color: "#6272a4", letterSpacing: 3, marginBottom: 6 }}>
          SCENE 3 — DEVQA SELF-HEALING LOOP
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, justifyContent: "center" }}>
          <div style={{ fontFamily: "Monaco, Menlo, monospace", fontSize: 24, color: "#cdd6f4", fontWeight: "bold" }}>
            Self-Healing in Action
          </div>
          <div style={{
            fontFamily: "Monaco, Menlo, monospace", fontSize: 12,
            background: "#313244", color: "#ffb86c",
            padding: "4px 12px", borderRadius: 6,
            border: "1px solid #ffb86c44",
          }}>
            {attemptLabel}
          </div>
        </div>
      </div>

      {/* Steps */}
      {STEPS.map((step) => (
        <StepCard key={step.label} {...step} startFrame={step.frame} />
      ))}

      {/* Progress bars */}
      <ProgressBar startFrame={75}  endFrame={146} color="#8be9fd" />
      <ProgressBar startFrame={148} endFrame={216} color="#ffb86c" />

      {/* Success glow */}
      {frame >= 218 && (
        <div style={{
          position: "absolute", inset: 0, pointerEvents: "none",
          background: "radial-gradient(ellipse at center, rgba(80,250,123,0.07) 0%, transparent 65%)",
          opacity: interpolate(frame, [218, 240], [0, 1], { extrapolateRight: "clamp" }),
        }} />
      )}
    </div>
  );
};
