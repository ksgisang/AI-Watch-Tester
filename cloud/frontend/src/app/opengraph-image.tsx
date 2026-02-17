import { ImageResponse } from "next/og";

export const runtime = "edge";

export const alt = "AWT — AI-Powered E2E Testing";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OGImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%)",
          fontFamily: "sans-serif",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            marginBottom: 24,
          }}
        >
          <div
            style={{
              fontSize: 72,
              fontWeight: 800,
              color: "#ffffff",
              letterSpacing: "-2px",
            }}
          >
            AWT
          </div>
        </div>
        <div
          style={{
            fontSize: 36,
            fontWeight: 600,
            color: "#60a5fa",
            marginBottom: 16,
          }}
        >
          AI-Powered E2E Testing
        </div>
        <div
          style={{
            fontSize: 22,
            color: "#94a3b8",
            maxWidth: 700,
            textAlign: "center",
            lineHeight: 1.5,
          }}
        >
          Just enter a URL. AI generates test scenarios, executes them, and
          reports results. No code required.
        </div>
      </div>
    ),
    { ...size }
  );
}
