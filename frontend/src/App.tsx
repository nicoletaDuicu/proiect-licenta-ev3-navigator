
import React, { useState, useCallback } from "react";
import MapView from "./components/MapView";
import Panel from "./components/Panel";
import { fetchMap, sendRoute, sendControl, setBaseUrl } from "./api/client";
import { useRobotStatus } from "./hooks/useRobotStatus";
import type { MapData } from "./types/types_index";

const DEMO_MAP: MapData = {
  nodes: {
    N1: [0, 0], N2: [0, 40], N3: [0, 80],
    N4: [84, 0], N5: [84, 40], N6: [84, 80],
  },
  edges: [
    { from: "N1", to: "N4", distance: 84 },
    { from: "N2", to: "N5", distance: 84 },
    { from: "N3", to: "N6", distance: 84 },
    { from: "N1", to: "N2", distance: 40 },
    { from: "N2", to: "N3", distance: 40 },
    { from: "N4", to: "N5", distance: 40 },
    { from: "N5", to: "N6", distance: 40 },
  ],
};

const STREAM_URL = "http://localhost:5001/video";

const App: React.FC = () => {
  const [mapData, setMapData]       = useState<MapData>(DEMO_MAP);
  const [connected, setConnected]   = useState(false);
  const [baseUrl, setBaseUrlState]  = useState("http://localhost:5000");
  const [selStart, setSelStart]     = useState<string | null>(null);
  const [selDest, setSelDest]       = useState<string | null>(null);
  const [showCamera, setShowCamera] = useState(false);

  const { state, error, connected: wsConnected } = useRobotStatus(connected, baseUrl);

  const handleConnect = useCallback(
    async (url: string) => {
      const cleanUrl = url.trim().replace(/\/$/, "");
      setBaseUrl(cleanUrl);
      setBaseUrlState(cleanUrl);
      try {
        const data = await fetchMap();
        setMapData(data);
        setConnected(true);
      } catch (e: unknown) {
        setConnected(false);
      }
    },
    []
  );

  const handleNodeClick = useCallback(
    (id: string) => {
      if (!connected) return;
      if (state?.status === "navigating") return;
      if (!selStart) {
        setSelStart(id);
      } else if (!selDest && id !== selStart) {
        setSelDest(id);
      } else {
        setSelStart(id);
        setSelDest(null);
      }
    },
    [connected, state, selStart, selDest]
  );

  const handleSendRoute = useCallback(async () => {
    if (!selStart || !selDest) return;
    try {
      const res = await sendRoute({ start: selStart, destination: selDest });
      if (res.ok) {
        setSelStart(null);
        setSelDest(null);
      }
    } catch (e: unknown) {}
  }, [selStart, selDest]);

  const handleControl = useCallback(
    async (cmd: string, extra?: Record<string, string>) => {
      try {
        await sendControl(cmd, extra);
      } catch (e: unknown) {}
    },
    []
  );

  const connStatus = connected && wsConnected
    ? state?.status === "navigating" || state?.status === "turning"
      ? "busy" : "ok"
    : "off";

  const connColors = { ok: "#4fffb0", busy: "#ffd166", off: "#3a4560" };

  const connLabel = connected && wsConnected
    ? "Sistem pornit."
    : "Neconectat";

  return (
    <div style={layoutStyles.root}>
      <header style={layoutStyles.header}>
        <span style={layoutStyles.logo}>
          EV3 <span style={{ color: "#ff6b6b" }}>//</span> NAVIGATOR
        </span>
        <div style={layoutStyles.headerSep} />

        <button
          onClick={() => setShowCamera(v => !v)}
          style={{
            background: showCamera ? "#1c2030" : "#07080c",
            border: "1px solid " + (showCamera ? "#4fffb0" : "#1c2030"),
            borderRadius: 6,
            color: showCamera ? "#4fffb0" : "#3a4560",
            fontFamily: "DM Mono, monospace",
            fontSize: 10,
            letterSpacing: 2,
            padding: "5px 12px",
            cursor: "pointer",
          }}
        >
          {showCamera ? "CAMERA ON" : "CAMERA OFF"}
        </button>

        <div style={layoutStyles.connPill}>
          <div
            style={{
              ...layoutStyles.dot,
              background: connColors[connStatus],
              boxShadow: connStatus !== "off"
                ? "0 0 8px " + connColors[connStatus]
                : "none",
            }}
          />
          <span style={{ color: "#3a4560", fontSize: 11 }}>
            {connLabel}
          </span>
        </div>
      </header>

      <main style={layoutStyles.mapWrap}>
        <div style={layoutStyles.mapBg} />

        {!showCamera && (
          <div style={{
            position: "relative",
            zIndex: 1,
            width: "100%",
            height: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}>
            <MapView
              mapData={mapData}
              state={state}
              selStart={selStart}
              selDest={selDest}
              onNodeClick={handleNodeClick}
            />
          </div>
        )}

        {showCamera && (
          <div style={{
            position: "relative",
            zIndex: 1,
            width: "100%",
            height: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "#07080c",
          }}>
            <img
              src={STREAM_URL}
              alt="Camera EV3"
              style={{
                maxWidth: "100%",
                maxHeight: "100%",
                objectFit: "contain",
                border: "1px solid #1c2030",
                borderRadius: 8,
              }}
            />
            <div style={{
              position: "absolute",
              top: 12,
              left: 12,
              background: "rgba(7,8,12,0.8)",
              border: "1px solid #1c2030",
              borderRadius: 6,
              padding: "8px 12px",
              fontFamily: "DM Mono, monospace",
              fontSize: 11,
              color: "#4fffb0",
            }}>
              <div>NOD: {state?.current_node ?? "—"}</div>
              <div>DEST: {state?.target_node ?? "—"}</div>
              <div>STATUS: {state?.status ?? "idle"}</div>
            </div>
          </div>
        )}
      </main>

      <aside style={layoutStyles.aside}>
        <Panel
          mapData={mapData}
          state={state}
          connected={connected && wsConnected}
          selStart={selStart}
          selDest={selDest}
          onConnect={handleConnect}
          onSendRoute={handleSendRoute}
          onControl={handleControl}
        />
      </aside>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Syne:wght@400;600;800&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #07080c; overflow: hidden; }
        input:focus { border-color: #4fffb0 !important; outline: none; }
        ::-webkit-scrollbar { width: 3px; }
        ::-webkit-scrollbar-thumb { background: #1c2030; border-radius: 2px; }
      `}</style>
    </div>
  );
};

const layoutStyles: Record<string, React.CSSProperties> = {
  root: {
    display: "grid",
    gridTemplateColumns: "1fr 320px",
    gridTemplateRows: "56px 1fr",
    gridTemplateAreas: '"hdr hdr" "map panel"',
    height: "100vh",
    fontFamily: "Syne, sans-serif",
    background: "#07080c",
    color: "#b8c4d8",
  },
  header: {
    gridArea: "hdr",
    background: "#0e1018",
    borderBottom: "1px solid #1c2030",
    display: "flex",
    alignItems: "center",
    padding: "0 24px",
    gap: 20,
  },
  logo: {
    fontFamily: "DM Mono, monospace",
    fontSize: 14,
    letterSpacing: 4,
    color: "#4fffb0",
    textTransform: "uppercase",
  },
  headerSep: { flex: 1 },
  connPill: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    background: "#07080c",
    border: "1px solid #1c2030",
    borderRadius: 20,
    padding: "6px 14px",
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: "50%",
    transition: "all 0.3s",
  },
  mapWrap: {
    gridArea: "map",
    position: "relative" as const,
    overflow: "hidden",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  mapBg: {
    position: "absolute" as const,
    inset: 0,
    backgroundImage:
      "radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px)",
    backgroundSize: "32px 32px",
  },
  aside: {
    gridArea: "panel",
    overflow: "hidden",
    display: "flex",
    flexDirection: "column" as const,
  },
};

export default App;