import type { CSSProperties } from "react";

import { MCP_SOURCES, MEASURED_AT, type McpSource } from "../sources";
import { JusticeStatue } from "./JusticeStatue";

// The stage keeps a 6:5 aspect ratio and the SVG scales uniformly, so viewBox units and the
// percentage positions of the captions describe the same points.
const VIEW = { width: 120, height: 100 };
const COLUMN_X = { left: 27, right: 93 };
// Where the statue sits in the stage: height as a share of the stage, centred both ways.
const STATUE = { height: 92, viewWidth: 200, viewHeight: 360 };
// The figure's outline in JusticeStatue's own units. Left: the robe edge from shoulder (y 128) to
// hem (y 292). Right: the lowered arm down to the hand (y 206), then the sword blade.
const ROBE = { top: 128, bottom: 292, left: [84, 64] };
const SWORD_ARM = { top: 133, hand: 206, shoulderX: 118, handX: 133, bladeX: 132 };

function outlineX(side: "left" | "right", y: number) {
  if (side === "left") {
    const [atTop, atBottom] = ROBE.left;
    return atTop + ((atBottom - atTop) * (y - ROBE.top)) / (ROBE.bottom - ROBE.top);
  }
  if (y >= SWORD_ARM.hand) return SWORD_ARM.bladeX;
  const t = Math.max(0, (y - SWORD_ARM.top) / (SWORD_ARM.hand - SWORD_ARM.top));
  return SWORD_ARM.shoulderX + (SWORD_ARM.handX - SWORD_ARM.shoulderX) * t;
}
// Leaders leave the robe's outline, spread between these heights (stage units).
const STEM = { top: 40, bottom: 76 };

function robeEdge(side: "left" | "right", stageY: number) {
  const scale = STATUE.height / STATUE.viewHeight;
  const statueLeft = VIEW.width / 2 - (STATUE.viewWidth * scale) / 2;
  const statueTop = (VIEW.height - STATUE.height) / 2;
  return statueLeft + outlineX(side, (stageY - statueTop) / scale) * scale;
}

interface Leader {
  source: McpSource;
  side: "left" | "right";
  from: { x: number; y: number };
  to: { x: number; y: number };
}

function column(sources: McpSource[], side: "left" | "right", top: number, bottom: number): Leader[] {
  const span = (count: number, start: number, end: number, index: number) =>
    count > 1 ? start + ((end - start) * index) / (count - 1) : (start + end) / 2;
  return sources.map((source, index) => {
    const stemY = span(sources.length, STEM.top, STEM.bottom, index);
    return {
      source,
      side,
      from: { x: robeEdge(side, stemY), y: stemY },
      to: { x: COLUMN_X[side], y: span(sources.length, top, bottom, index) },
    };
  });
}

export function SourcePlate() {
  // Sources the analysis queries sit on the right, those it only could reach on the left.
  const leaders = [
    ...column(MCP_SOURCES.filter((source) => source.searched), "right", 12, 88),
    ...column(MCP_SOURCES.filter((source) => !source.searched), "left", 16, 84),
  ];

  return (
    <figure className="plate">
      <div className="plate-stage">
        <svg className="plate-lines" viewBox={`0 0 ${VIEW.width} ${VIEW.height}`} aria-hidden="true">
          {leaders.map(({ source, from, to }, index) => (
            <g key={source.name} className={source.searched ? "leader is-searched" : "leader"} style={{ "--order": index } as CSSProperties}>
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} pathLength={1} />
              <circle cx={to.x} cy={to.y} r={0.9} />
            </g>
          ))}
        </svg>

        <JusticeStatue className="plate-statue" />

        <ul className="plate-captions">
          {leaders.map(({ source, side, to }, index) => (
            <li
              key={source.name}
              className={`caption caption-${side}`}
              style={
                {
                  top: `${(to.y / VIEW.height) * 100}%`,
                  [side === "right" ? "left" : "right"]:
                    side === "right"
                      ? `${((to.x + 2) / VIEW.width) * 100}%`
                      : `${((VIEW.width - to.x + 2) / VIEW.width) * 100}%`,
                  "--order": index,
                } as CSSProperties
              }
            >
              <span className="caption-name">{source.name}</span>
              <span className="caption-detail">{source.detail}</span>
            </li>
          ))}
        </ul>
      </div>

      <figcaption className="plate-note">
        Sources reachable through Yargı MCP. Filled points on the right are searched in every analysis,
        open points on the left are reachable but not used here. Decision counts from the Bedesten index,{" "}
        {MEASURED_AT}.
      </figcaption>
    </figure>
  );
}
