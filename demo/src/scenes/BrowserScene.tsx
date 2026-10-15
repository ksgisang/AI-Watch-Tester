import React from "react";
import { useCurrentFrame, useVideoConfig, interpolate, spring } from "remotion";

// Mock English login page rendered in React — no screenshot needed
function MockLoginPage({ highlightButton, showSuccess }: { highlightButton: boolean; showSuccess: boolean }) {
  return (
    <div style={{
      background: "#f5f7fa",
      minHeight: 460,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "Arial, sans-serif",
    }}>
      <div style={{
        background: "#fff",
        borderRadius: 12,
        padding: "40px 48px",
        width: 360,
        boxShadow: "0 4px 24px rgba(0,0,0,0.10)",
        position: "relative",
      }}>
        {/* Logo */}
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <div style={{
            width: 48, height: 48, borderRadius: 10,
            background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
            margin: "0 auto 12px",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "#fff", fontSize: 22, fontWeight: "bold",
          }}>A</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: "#1a1a2e" }}>AcademyApp</div>
          <div style={{ fontSize: 13, color: "#888", marginTop: 4 }}>Sign in to your account</div>
        </div>

        {/* Email field */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#374151", marginBottom: 6 }}>Email address</div>
          <div style={{
            border: "1.5px solid #d1d5db", borderRadius: 8,
            padding: "10px 14px", fontSize: 14, color: "#374151", background: "#f9fafb",
          }}>admin@academy.com</div>
        </div>

        {/* Password field */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#374151", marginBottom: 6 }}>Password</div>
          <div style={{
            border: "1.5px solid #d1d5db", borderRadius: 8,
            padding: "10px 14px", fontSize: 14, color: "#374151", background: "#f9fafb",
          }}>••••••••</div>
        </div>

        {/* Login button */}
        <div style={{
          background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
          color: "#fff",
          textAlign: "center",
          padding: "12px",
          borderRadius: 8,
          fontSize: 15,
          fontWeight: 700,
          cursor: "pointer",
          position: "relative",
          border: highlightButton ? "3px solid #ff5050" : "3px solid transparent",
          boxShadow: highlightButton ? "0 0 0 4px rgba(255,80,80,0.25)" : "none",
          transition: "border 0.2s",
        }}>
          Sign In
        </div>

        {/* Forgot password */}
        <div style={{ textAlign: "center", marginTop: 16, fontSize: 13, color: "#6366f1" }}>
          Forgot your password?
        </div>

        {/* Success overlay */}
        {showSuccess && (
          <div style={{
            position: "absolute", top: 12, left: "50%",
            transform: "translateX(-50%)",
            background: "#22c55e",
            color: "#fff",
            padding: "8px 24px",
            borderRadius: 8,
            fontSize: 14,
            fontWeight: 700,
            whiteSpace: "nowrap",
            boxShadow: "0 4px 20px rgba(34,197,94,0.4)",
          }}>
            ✅ Login successful
          </div>
        )}
      </div>
    </div>
  );
}

const STEP_LOGS = [
  { frame: 30,  text: "▶  Navigating to https://academy.com/login",   color: "#8be9fd" },
  { frame: 65,  text: "✔  Page loaded — DOM stable (423ms)",           color: "#50fa7b" },
  { frame: 90,  text: "▶  Locating email field → input[type=email]",  color: "#8be9fd" },
  { frame: 110, text: "✔  Typing  admin@academy.com",                  color: "#50fa7b" },
  { frame: 130, text: "▶  Locating password field → input[type=password]", color: "#8be9fd" },
  { frame: 148, text: "✔  Typing  ••••••••",                           color: "#50fa7b" },
  { frame: 165, text: "▶  Clicking  Sign In  button",                  color: "#ffb86c" },
  { frame: 200, text: "✔  Assert: URL contains /dashboard  [PASS]",   color: "#50fa7b" },
  { frame: 225, text: "✔  Assert: welcome message visible  [PASS]",   color: "#50fa7b" },
  { frame: 248, text: "✅  Scenario PASSED — 3/3 steps (1.8s)",        color: "#50fa7b" },
];

export const BrowserScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 15],   [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [280, 300], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  // Scan line (frame 30~90)
  const scanOpacity = interpolate(frame, [30, 45, 80, 95], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const scanY = interpolate(frame, [30, 130], [0, 460], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  // Red border on button (frame 155~200)
  const highlightButton = frame >= 155 && frame <= 210;

  // Click ripple
  const rippleScale = spring({ fps, frame: frame - 168, config: { damping: 40, stiffness: 180 } });
  const rippleOpacity = interpolate(frame, [168, 205], [0.9, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  // Success
  const showSuccess = frame >= 220;

  // Log lines
  const visibleLogs = STEP_LOGS.filter((l) => l.frame <= frame);

  return (
    <div style={{
      width, height, background: "#1e1e2e",
      display: "flex", gap: 0,
      opacity: fadeIn * fadeOut,
    }}>
      {/* Left: browser */}
      <div style={{ flex: "0 0 540px", display: "flex", flexDirection: "column", padding: "28px 0 28px 32px" }}>
        <div style={{ borderRadius: 10, overflow: "hidden", boxShadow: "0 20px 60px rgba(0,0,0,0.5)", flex: 1 }}>
          {/* URL bar */}
          <div style={{ background: "#313244", padding: "9px 14px", display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ display: "flex", gap: 6 }}>
              {["#ff5f57","#febc2e","#28c840"].map((c) => (
                <div key={c} style={{ width: 11, height: 11, borderRadius: "50%", background: c }} />
              ))}
            </div>
            <div style={{ flex: 1, background: "#1e1e2e", borderRadius: 5, padding: "4px 12px", fontFamily: "Monaco, Menlo, monospace", fontSize: 11, color: "#8be9fd" }}>
              https://academy.com/login
            </div>
          </div>

          {/* Page */}
          <div style={{ position: "relative" }}>
            <MockLoginPage highlightButton={highlightButton} showSuccess={showSuccess} />

            {/* Scan line */}
            <div style={{
              position: "absolute", top: 0, left: 0, right: 0,
              transform: `translateY(${scanY}px)`,
              height: 2,
              background: "linear-gradient(90deg, transparent, #00d4aa, transparent)",
              opacity: scanOpacity,
              boxShadow: "0 0 16px #00d4aa",
            }} />

            {/* Click ripple */}
            {frame >= 168 && (
              <div style={{
                position: "absolute",
                bottom: "28%", left: "50%",
                transform: `translate(-50%, 50%) scale(${rippleScale})`,
                width: 50, height: 50, borderRadius: "50%",
                border: "2.5px solid #ff5050",
                opacity: rippleOpacity,
              }} />
            )}

            {/* AWT badge */}
            <div style={{
              position: "absolute", top: 8, right: 8,
              background: "rgba(0,212,170,0.92)", color: "#1e1e2e",
              padding: "3px 10px", borderRadius: 5,
              fontFamily: "Monaco, Menlo, monospace", fontSize: 11, fontWeight: "bold",
              opacity: frame < 250 ? 1 : interpolate(frame, [250, 270], [1, 0], { extrapolateRight: "clamp" }),
            }}>
              AWT
            </div>
          </div>
        </div>
      </div>

      {/* Right: step log */}
      <div style={{ flex: 1, padding: "28px 24px 28px 20px", display: "flex", flexDirection: "column", justifyContent: "flex-start" }}>
        <div style={{ fontFamily: "Monaco, Menlo, monospace", fontSize: 12, color: "#6272a4", letterSpacing: 2, marginBottom: 14 }}>
          STEP LOG
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {visibleLogs.map((l, i) => (
            <div key={i} style={{
              fontFamily: "Monaco, Menlo, monospace",
              fontSize: 12,
              color: l.color,
              opacity: interpolate(frame, [l.frame, l.frame + 8], [0, 1], { extrapolateRight: "clamp", extrapolateLeft: "clamp" }),
              lineHeight: 1.6,
            }}>
              {l.text}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
