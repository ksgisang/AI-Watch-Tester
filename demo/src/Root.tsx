import React from "react";
import { Composition, Series } from "remotion";
import { TerminalScene } from "./scenes/TerminalScene";
import { BrowserScene } from "./scenes/BrowserScene";
import { DevQAScene } from "./scenes/DevQAScene";

const FPS = 30;
const SCENE_FRAMES = FPS * 10; // 10초 per scene = 300 frames

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="AWT-Demo"
        component={() => (
          <Series>
            <Series.Sequence durationInFrames={SCENE_FRAMES}>
              <TerminalScene />
            </Series.Sequence>
            <Series.Sequence durationInFrames={SCENE_FRAMES}>
              <BrowserScene />
            </Series.Sequence>
            <Series.Sequence durationInFrames={SCENE_FRAMES}>
              <DevQAScene />
            </Series.Sequence>
          </Series>
        )}
        durationInFrames={SCENE_FRAMES * 3}
        fps={FPS}
        width={1280}
        height={720}
      />
    </>
  );
};
