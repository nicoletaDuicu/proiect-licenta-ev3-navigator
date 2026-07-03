// components/MapView.tsx
import React, { useMemo } from "react";
import type { MapData, SystemState } from "../types/types_index";

interface Props {
  mapData: MapData;
  state: SystemState | null;
  selStart: string | null;
  selDest: string | null;
  onNodeClick: (id: string) => void;
}

const PAD = 60;
const SVG_W = 600;
const SVG_H = 600;

const MapView: React.FC<Props> = ({
  mapData,
  state,
  selStart,
  selDest,
  onNodeClick,
}) => {
  const nodes = mapData.nodes;
  const edges = mapData.edges;
  const route = state?.route ?? [];
  const currentNode = state?.current_node ?? null;

  
  const { nodePositions, bounds } = useMemo(() => {
    const coords = Object.values(nodes);
    if (coords.length === 0) {
      return { nodePositions: {}, bounds: { minX: 0, maxX: 100, minY: 0, maxY: 100 } };
    }

    const xs = coords.map(c => c[0]);
    const ys = coords.map(c => c[1]);
    const b = {
      minX: Math.min(...xs),
      maxX: Math.max(...xs),
      minY: Math.min(...ys),
      maxY: Math.max(...ys),
    };

    const rangeX = b.maxX - b.minX || 1;
    const rangeY = b.maxY - b.minY || 1;
    const drawW = SVG_W - PAD * 2;
    const drawH = SVG_H - PAD * 2;

    
    const scale = Math.min(drawW / rangeX, drawH / rangeY);
    const usedW = rangeX * scale;
    const usedH = rangeY * scale;

    const offsetX = PAD + (drawW - usedW) / 2;
    const offsetY = PAD + (drawH - usedH) / 2;

    const pos: Record<string, { x: number; y: number }> = {};
    Object.entries(nodes).forEach(([id, [cx, cy]]) => {
      pos[id] = {
        x: offsetX + (cx - b.minX) * scale,
        y: offsetY + (b.maxY - cy) * scale, 
      };
    });

    return { nodePositions: pos, bounds: b };
  }, [nodes]);

  const nodeClass = (id: string): string => {
    if (id === selStart) return "node-start";
    if (id === selDest) return "node-dest";
    if (id === currentNode) return "node-current";
    if (route.includes(id)) return "node-route";
    return "node-default";
  };

  const currentIdx = route.indexOf(currentNode ?? "");

  return (
    <svg
      width="100%"
      height="100%"
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      preserveAspectRatio="xMidYMid meet"
      style={{ display: "block", maxHeight: "100%" }}
    >
      <defs>
        <pattern id="grid" width="48" height="48" patternUnits="userSpaceOnUse">
          <path d="M 48 0 L 0 0 0 48" fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
        </pattern>
      </defs>

      <rect width={SVG_W} height={SVG_H} fill="url(#grid)" />

      {}
      {edges.map((edge, i) => {
        const a = nodePositions[edge.from];
        const b = nodePositions[edge.to];
        if (!a || !b) return null;
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2;
        const isVertical = Math.abs(a.x - b.x) < 10;

        return (
          <g key={`edge-${i}`}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke="#131a28" strokeWidth={22} strokeLinecap="round" />
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke="#1e2c42" strokeWidth={1.5} strokeDasharray="7 7" fill="none" />
            <text
              x={isVertical ? mx - 18 : mx}
              y={isVertical ? my : my - 10}
              fill="#2a3a55"
              fontFamily="'DM Mono', monospace"
              fontSize={10}
              textAnchor="middle"
            >
              {edge.distance}cm
            </text>
          </g>
        );
      })}

      {}
      {route.length >= 2 &&
        route.slice(Math.max(currentIdx, 0), -1).map((nodeId, i) => {
          const nextId = route[Math.max(currentIdx, 0) + i + 1];
          const a = nodePositions[nodeId];
          const b = nodePositions[nextId];
          if (!a || !b) return null;
          return (
            <line key={`route-${i}`}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke="#4fffb0" strokeWidth={3}
              strokeDasharray="6 5" fill="none" opacity={0.55}
              style={{ animation: "dashFlow 0.8s linear infinite" }}
            />
          );
        })}

      {}
      {Object.entries(nodePositions).map(([id, pos]) => {
        const cls = nodeClass(id);
        const colors: Record<string, { fill: string; stroke: string; text: string; glow: string }> = {
          "node-default": { fill: "#0e1018", stroke: "#2a3348", text: "#b8c4d8", glow: "none" },
          "node-start":   { fill: "#0a2018", stroke: "#4fffb0", text: "#4fffb0", glow: "drop-shadow(0 0 8px #4fffb0)" },
          "node-dest":    { fill: "#200a0a", stroke: "#ff6b6b", text: "#ff6b6b", glow: "drop-shadow(0 0 10px #ff6b6b)" },
          "node-current": { fill: "#0a2018", stroke: "#4fffb0", text: "#4fffb0", glow: "drop-shadow(0 0 12px #4fffb0)" },
          "node-route":   { fill: "#0a1828", stroke: "#4cc9f0", text: "#4cc9f0", glow: "drop-shadow(0 0 6px #4cc9f0)" },
        };
        const c = colors[cls];

        return (
          <g key={id} style={{ cursor: "pointer", filter: c.glow }} onClick={() => onNodeClick(id)}>
            <circle cx={pos.x} cy={pos.y} r={24} fill="none"
              stroke={c.stroke} strokeWidth={1} opacity={0.3} />
            <circle cx={pos.x} cy={pos.y} r={18} fill={c.fill}
              stroke={c.stroke} strokeWidth={cls === "node-default" ? 1.5 : 2} />
            <text x={pos.x} y={pos.y} fill={c.text}
              fontFamily="'DM Mono', monospace" fontSize={13}
              fontWeight={500} textAnchor="middle" dominantBaseline="central">
              {id}
            </text>
          </g>
        );
      })}

      {}
      {currentNode && nodePositions[currentNode] && (
        <g transform={`translate(${nodePositions[currentNode].x}, ${nodePositions[currentNode].y})`}
          style={{ transition: "transform 0.5s ease" }}>
          <circle r={9} fill="#4fffb0" opacity={0.9} />
          <circle r={14} fill="none" stroke="#4fffb0" strokeWidth={1} opacity={0.3}
            style={{ animation: "ping 1.5s ease-out infinite" }} />
        </g>
      )}

      <style>{`
        @keyframes dashFlow { to { stroke-dashoffset: -22; } }
        @keyframes ping { 0% { r: 14; opacity: 0.4; } 100% { r: 28; opacity: 0; } }
      `}</style>
    </svg>
  );
};

export default MapView;