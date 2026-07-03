// components/Panel.tsx
import React, { useState } from "react";
import type { MapData, SystemState, RobotStatus } from "../types/types_index";

interface Props {
  mapData: MapData | null;
  state: SystemState | null;
  connected: boolean;
  selStart: string | null;
  selDest: string | null;
  onConnect: (url: string) => void;
  onSendRoute: () => void;
  onControl: (cmd: string, extra?: Record<string, string>) => void;
}

const STATUS_LABELS: Record<RobotStatus, string> = {
  idle: "IDLE",
  waiting: "ASTEPT",
  navigating: "IN MERS",
  turning: "VIRAJ",
  arrived: "AJUNS",
  error: "EROARE",
};

const STATUS_COLORS: Record<RobotStatus, string> = {
  idle: "#3a4560",
  waiting: "#ffd166",
  navigating: "#4fffb0",
  turning: "#ffd166",
  arrived: "#4fffb0",
  error: "#ff6b6b",
};

const Panel: React.FC<Props> = ({
  mapData,
  state,
  connected,
  selStart,
  selDest,
  onConnect,
  onSendRoute,
  onControl,
}) => {
  const [ipVal, setIpVal] = useState("http://192.168.1.100:5000");

  const canSend =
    connected && selStart && selDest && state?.status !== "navigating";

  const nodeIds = mapData ? Object.keys(mapData.nodes) : [];

  return (
    <div style={styles.panel}>
      {/* CONEXIUNE */}
      <div style={styles.sec}>
        <div style={styles.secTitle}>CONEXIUNE BACKEND</div>
        <div style={styles.row}>
          <input
            style={styles.input}
            value={ipVal}
            onChange={(e) => setIpVal(e.target.value)}
            placeholder="http://IP:5000"
          />
          <button style={styles.btnPrimary} onClick={() => onConnect(ipVal)}>
            CONN
          </button>
        </div>
      </div>

      {/* SELECTIE TRASEU */}
      <div style={styles.sec}>
        <div style={styles.secTitle}>SELECTIE TRASEU</div>
        <div style={styles.nodeSelRow}>
          <div>
            <div style={styles.selLabel}>START</div>
            <div style={{ ...styles.selVal, color: "#4fffb0" }}>
              {selStart ?? "—"}
            </div>
          </div>
          <div>
            <div style={styles.selLabel}>DESTINATIE</div>
            <div style={{ ...styles.selVal, color: "#ff6b6b" }}>
              {selDest ?? "—"}
            </div>
          </div>
        </div>
        <button
          style={{
            ...styles.btnPrimary,
            width: "100%",
            marginTop: 10,
            padding: "10px 0",
            opacity: canSend ? 1 : 0.35,
            cursor: canSend ? "pointer" : "not-allowed",
          }}
          onClick={onSendRoute}
          disabled={!canSend}
        >
          TRIMITE TRASEU
        </button>
      </div>

      {/* TELEMETRIE */}
      <div style={styles.sec}>
        <div style={styles.secTitle}>TELEMETRIE ROBOT</div>
        <div style={styles.telemGrid}>
          <Tcard label="NOD CURENT" value={state?.current_node ?? "—"} color="#4fffb0" />
          <Tcard label="DESTINATIE" value={state?.target_node ?? "—"} color="#ffd166" />
          <Tcard
            label="STATUS"
            value={state ? STATUS_LABELS[state.status] : "—"}
            color={state ? STATUS_COLORS[state.status] : "#3a4560"}
          />
          <Tcard
            label="DISTANTA"
            value={state?.total_distance ? `${state.total_distance}cm` : "—"}
            color="#4cc9f0"
          />
        </div>
      </div>

      {/* RUTA ACTIVA */}
      <div style={styles.sec}>
        <div style={styles.secTitle}>RUTA ACTIVA</div>
        <RouteStrip route={state?.route ?? []} current={state?.current_node ?? null} />
      </div>

      {/* POZITIE MANUALA */}
      <div style={styles.sec}>
        <div style={styles.secTitle}>POZITIE MANUALA</div>
        <div style={styles.posBtns}>
          {nodeIds.map((id) => (
            <button
              key={id}
              style={{
                ...styles.btnSmall,
                ...(state?.current_node === id ? styles.btnActive : {}),
              }}
              onClick={() => onControl("set_position", { node: id })}
            >
              {id}
            </button>
          ))}
        </div>
      </div>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* CONTROL */}
      <div style={styles.ctrlRow}>
        <button
          style={{ ...styles.btnWarn, flex: 1 }}
          onClick={() => onControl("reset")}
        >
          RESET
        </button>
        <button
          style={{ ...styles.btnDanger, flex: 1 }}
          onClick={() => onControl("stop")}
        >
          STOP
        </button>
      </div>
    </div>
  );
};

const Tcard: React.FC<{
  label: string;
  value: string;
  color: string;
}> = ({ label, value, color }) => (
  <div style={styles.tcard}>
    <div style={styles.tcardLabel}>{label}</div>
    <div style={{ ...styles.tcardVal, color }}>{value}</div>
  </div>
);

const RouteStrip: React.FC<{
  route: string[];
  current: string | null;
}> = ({ route, current }) => {
  if (!route.length)
    return (
      <span style={{ fontFamily: "DM Mono, monospace", fontSize: 10, color: "#3a4560" }}>
        Nicio ruta activa
      </span>
    );

  const ci = route.indexOf(current ?? "");
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
      {route.map((n, i) => {
        const isDone = i < ci;
        const isCur = i === ci;
        return (
          <React.Fragment key={n}>
            <span
              style={{
                fontFamily: "DM Mono, monospace",
                fontSize: 12,
                padding: "3px 10px",
                borderRadius: 3,
                border: `1px solid ${isCur ? "#4cc9f0" : isDone ? "#4fffb0" : "#2a3348"}`,
                color: isCur ? "#4cc9f0" : isDone ? "#4fffb0" : "#3a4560",
                background: isCur ? "rgba(76,201,240,0.08)" : "transparent",
                opacity: isDone ? 0.5 : 1,
              }}
            >
              {n}
            </span>
            {i < route.length - 1 && (
              <span style={{ color: "#3a4560", fontSize: 10, fontFamily: "DM Mono, monospace" }}>→</span>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
};

const styles: Record<string, React.CSSProperties> = {
  panel: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    background: "#0e1018",
    borderLeft: "1px solid #1c2030",
    overflow: "hidden",
  },
  sec: {
    padding: "14px 18px",
    borderBottom: "1px solid #1c2030",
  },
  secTitle: {
    fontFamily: "DM Mono, monospace",
    fontSize: 9,
    letterSpacing: 3,
    color: "#3a4560",
    textTransform: "uppercase" as const,
    marginBottom: 10,
  },
  row: {
    display: "flex",
    gap: 8,
  },
  input: {
    flex: 1,
    background: "#07080c",
    border: "1px solid #1c2030",
    borderRadius: 4,
    color: "#b8c4d8",
    fontFamily: "DM Mono, monospace",
    fontSize: 11,
    padding: "7px 10px",
    outline: "none",
  },
  btnPrimary: {
    background: "transparent",
    border: "1px solid #4fffb0",
    borderRadius: 4,
    color: "#4fffb0",
    fontFamily: "Syne, sans-serif",
    fontSize: 11,
    fontWeight: 600,
    padding: "7px 14px",
    cursor: "pointer",
    letterSpacing: 1,
  },
  btnWarn: {
    background: "transparent",
    border: "1px solid #ffd166",
    borderRadius: 4,
    color: "#ffd166",
    fontFamily: "Syne, sans-serif",
    fontSize: 12,
    fontWeight: 600,
    padding: "10px",
    cursor: "pointer",
    letterSpacing: 1,
  },
  btnDanger: {
    background: "transparent",
    border: "1px solid #ff6b6b",
    borderRadius: 4,
    color: "#ff6b6b",
    fontFamily: "Syne, sans-serif",
    fontSize: 12,
    fontWeight: 600,
    padding: "10px",
    cursor: "pointer",
    letterSpacing: 1,
  },
  btnSmall: {
    background: "transparent",
    border: "1px solid #1c2030",
    borderRadius: 4,
    color: "#3a4560",
    fontFamily: "DM Mono, monospace",
    fontSize: 11,
    padding: "5px 12px",
    cursor: "pointer",
  },
  btnActive: {
    borderColor: "#4fffb0",
    color: "#4fffb0",
    background: "rgba(79,255,176,0.07)",
  },
  nodeSelRow: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 8,
    marginBottom: 8,
  },
  selLabel: {
    fontFamily: "DM Mono, monospace",
    fontSize: 9,
    letterSpacing: 2,
    color: "#3a4560",
    marginBottom: 4,
  },
  selVal: {
    fontFamily: "DM Mono, monospace",
    fontSize: 22,
    fontWeight: 500,
    minHeight: 30,
  },
  telemGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 8,
  },
  tcard: {
    background: "#07080c",
    border: "1px solid #1c2030",
    borderRadius: 4,
    padding: "9px 12px",
  },
  tcardLabel: {
    fontFamily: "DM Mono, monospace",
    fontSize: 8,
    letterSpacing: 2,
    color: "#3a4560",
    marginBottom: 4,
  },
  tcardVal: {
    fontFamily: "DM Mono, monospace",
    fontWeight: 500,
    fontSize: 16,
  },
  posBtns: {
    display: "flex",
    flexWrap: "wrap" as const,
    gap: 6,
  },
  ctrlRow: {
    display: "flex",
    gap: 8,
    padding: "12px 18px",
    borderTop: "1px solid #1c2030",
  },
};

export default Panel;