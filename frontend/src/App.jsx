import { useState, useRef, useEffect } from "react";

const API = "http://localhost:8000";
const BG = "#121212";
const INK = "#EDEAE0";
const RED = "#FF5A3C";
const FADE = "#8F8B80";

export default function App() {
  const [messages, setMessages] = useState([]);
  const [activity, setActivity] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [threadId, setThreadId] = useState(null);
  const [pending, setPending] = useState(false);
  const [approved, setApproved] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [orderNum, setOrderNum] = useState(null);
  const feedRef = useRef(null);

  useEffect(() => { feedRef.current?.scrollTo(0, feedRef.current.scrollHeight); }, [messages]);

  const pad = (n) => String(n).padStart(2, "0");
  const addMsg = (who, text) => setMessages(m => [...m, { n: pad(m.length + 1), who, text }]);
  const addLog = (text) => setActivity(a => [...a, text]);

  const send = async () => {
    const msg = input.trim();
    if (!msg || loading) return;
    setInput("");
    addMsg("YOU", msg);
    setLoading(true);
    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, thread_id: threadId }),
      });
      const data = await res.json();
      if (!threadId) { setThreadId(data.thread_id); setOrderNum(String(Math.floor(Math.random() * 900) + 100)); }
      addMsg("AGENT", data.reply);
      addLog(`Agent replied · step ${pad(messages.length + 2)}`);
      if (data.pending_approval) { setPending(true); addLog("Awaiting approval — nothing placed yet"); }
    } catch { addMsg("AGENT", "Connection error. Is the backend running?"); }
    setLoading(false);
  };

  const handleApprove = async (yes) => {
    setPending(false); setApproved(yes); setLoading(true);
    try {
      const res = await fetch(`${API}/approve`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, approved: yes }),
      });
      const data = await res.json();
      addMsg("AGENT", data.reply || (yes ? "Order placed!" : "Order cancelled."));
      addLog(yes ? "Order approved and placed" : "Order declined");
    } catch { addMsg("AGENT", "Something went wrong."); }
    setLoading(false);
  };

  const reset = () => {
    setMessages([]); setActivity([]); setThreadId(null);
    setPending(false); setApproved(false); setOrderNum(null);
  };

  return (
    <div style={{ background: BG, height: "100vh", display: "flex", flexDirection: "column", fontFamily: "'Inter',sans-serif", color: INK, overflow: "hidden" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;500;600;700&display=swap');
        * { box-sizing:border-box; margin:0; }
        .h-red:hover  { background:${RED}!important; border-color:${RED}!important; color:${BG}!important; }
        .h-fill:hover { background:${INK}!important; color:${BG}!important; }
        .mrow:hover   { background:rgba(237,234,224,0.08); }
        input::placeholder { color:${FADE}; }
        input:focus, button:focus-visible { outline:2px solid ${INK}; outline-offset:2px; }
        ::-webkit-scrollbar { width:3px; } ::-webkit-scrollbar-thumb { background:${FADE}; }
      `}</style>

      {/* ── Top bar ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 40px", borderBottom: `1px solid ${INK}`, flexShrink: 0 }}>
        <span style={{ fontSize: 11, letterSpacing: "0.1em", color: FADE }}>SWIGGYPILOT</span>
        <div style={{ position: "relative" }}>
          <button onClick={() => setMenuOpen(v => !v)} aria-label="Account"
            style={{ width: 32, height: 32, borderRadius: "50%", border: `1px solid ${INK}`, background: menuOpen ? INK : "transparent", color: menuOpen ? BG : INK, fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
            DK
          </button>
          {menuOpen && (
            <div style={{ position: "absolute", right: 0, top: 40, width: 260, background: BG, border: `1px solid ${INK}`, zIndex: 20 }}>
              <div style={{ padding: "14px 18px", borderBottom: `1px solid ${INK}` }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>Deepak</div>
                <div style={{ fontSize: 11, color: FADE, marginTop: 2 }}>+91 9XXXX XXXXX · Swiggy linked</div>
              </div>
              <div style={{ padding: "12px 18px", borderBottom: `1px solid ${INK}` }}>
                <div style={{ fontSize: 10, letterSpacing: "0.08em", color: FADE, marginBottom: 8 }}>SAVED ADDRESSES</div>
                {[["HOME", "B-12 Vaishali Nagar, Jaipur"], ["WORK", "JKLU Campus, Ajmer Road"]].map(([t, l], i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "4px 0" }}>
                    <span style={{ color: FADE, minWidth: 44 }}>{t}</span><span style={{ textAlign: "right" }}>{l}</span>
                  </div>
                ))}
              </div>
              {["Past orders", "Track a live order", "Payment method · COD"].map((t, i) => (
                <button key={i} className="mrow" style={{ width: "100%", textAlign: "left", background: "transparent", border: "none", borderBottom: `1px solid ${INK}`, color: INK, padding: "10px 18px", fontSize: 12, cursor: "pointer" }}>{t}</button>
              ))}
              <button className="mrow" style={{ width: "100%", textAlign: "left", background: "transparent", border: "none", color: RED, padding: "10px 18px", fontSize: 12, cursor: "pointer" }}>Log out</button>
            </div>
          )}
        </div>
      </div>

      {/* ── Hero (compact) ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 40px", flexShrink: 0 }}>
        <h1 style={{ fontFamily: "'Anton',sans-serif", fontSize: 52, lineHeight: 1, textTransform: "uppercase" }}>
          JUST SAY <span style={{ color: RED }}>IT.</span>
        </h1>
        <p style={{ maxWidth: 240, fontSize: 12, lineHeight: 1.6, color: FADE, textAlign: "right" }}>
          You type the request. SwiggyPilot finds it, carts it, and waits for your yes before anything is real.
        </p>
      </div>

      <div style={{ borderTop: `2px solid ${INK}`, flexShrink: 0 }} />

      {/* ── Status bar ── */}
      <div style={{ padding: "10px 40px", borderBottom: `1px solid ${INK}`, fontSize: 12, flexShrink: 0 }}>
        {loading ? "Agent is thinking…" : pending ? "Waiting for your approval — nothing placed yet." : "No apps opened. No menus scrolled. Just this."}
      </div>

      {/* ── Main two-column (fills remaining space) ── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* Left: chat */}
        <div style={{ flex: "1 1 0", borderRight: `1px solid ${INK}`, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Feed */}
          <div ref={feedRef} style={{ flex: 1, overflowY: "auto", padding: "20px 32px", display: "flex", flexDirection: "column", gap: 16 }}>
            {messages.length === 0 && <p style={{ color: FADE, fontSize: 13 }}>Start by telling SwiggyPilot what you want.</p>}
            {messages.map((m, i) => (
              <div key={i} style={{ display: "flex", gap: 12 }}>
                <span style={{ fontSize: 11, color: FADE, paddingTop: 2, minWidth: 20, flexShrink: 0 }}>{m.n}</span>
                <div>
                  <div style={{ fontSize: 10, letterSpacing: "0.08em", color: m.who === "YOU" ? FADE : RED, marginBottom: 2, fontWeight: 600 }}>{m.who}</div>
                  <p style={{ margin: 0, fontSize: 14, lineHeight: 1.55 }}>{m.text}</p>
                </div>
              </div>
            ))}
            {loading && (
              <div style={{ display: "flex", gap: 12 }}>
                <span style={{ fontSize: 11, color: FADE, paddingTop: 2, minWidth: 20 }}>{pad(messages.length + 1)}</span>
                <div>
                  <div style={{ fontSize: 10, letterSpacing: "0.08em", color: RED, marginBottom: 2, fontWeight: 600 }}>AGENT</div>
                  <p style={{ margin: 0, fontSize: 14, color: FADE }}>…</p>
                </div>
              </div>
            )}
          </div>

          {/* Input + actions row */}
          <div className="bottom-bar">
            <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === "Enter" && send()}
              placeholder="Tell it what you need"
              style={{ flex: 1, background: "transparent", border: "none", padding: "14px 32px", fontSize: 14, color: INK }} />
            <button onClick={send} disabled={loading} className="h-new"
              style={{ background: BG, color: INK, border: "none", padding: "0 28px", borderLeft: "1px solid #3A362E", fontSize: 11, letterSpacing: "0.08em", cursor: "pointer", flexShrink: 0 }}>
              SEND
            </button>
            <button onClick={reset} className="h-new"
              style={{ background: BG, color: INK, border: "none", padding: "0 28px", borderLeft: "1px solid #3A362E", fontSize: 11, letterSpacing: "0.08em", cursor: "pointer", flexShrink: 0 }}>
              NEW ORDER
            </button>
          </div>
        </div>

        {/* Right: order panel */}
        <div style={{ width: 340, flexShrink: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 24px", borderBottom: `1px solid ${INK}`, fontSize: 10, letterSpacing: "0.08em", color: FADE, flexShrink: 0 }}>
            <span>CURRENT ORDER</span>
            <span>{orderNum ? `ORDER #${orderNum}` : "—"}</span>
          </div>

          <div style={{ display: "flex", borderBottom: `1px solid ${INK}`, flexShrink: 0 }}>
            <div style={{ flex: 1, padding: "16px 24px", borderRight: `1px solid ${INK}` }}>
              <div style={{ fontSize: 10, letterSpacing: "0.08em", color: FADE, marginBottom: 4 }}>ITEMS</div>
              <div style={{ fontFamily: "'Anton',sans-serif", fontSize: 40, lineHeight: 1 }}>—</div>
            </div>
            <div style={{ flex: 1, padding: "16px 24px" }}>
              <div style={{ fontSize: 10, letterSpacing: "0.08em", color: FADE, marginBottom: 4 }}>TOTAL · COD</div>
              <div style={{ fontFamily: "'Anton',sans-serif", fontSize: 40, lineHeight: 1, color: RED }}>—</div>
            </div>
          </div>

          {/* Activity log */}
          <div style={{ flex: 1, overflowY: "auto", padding: "16px 24px", borderBottom: `1px solid ${INK}` }}>
            <div style={{ fontSize: 10, letterSpacing: "0.08em", color: FADE, marginBottom: 10 }}>
              ACTIVITY LOG &nbsp;·&nbsp; {activity.length} updates
            </div>
            {activity.length === 0
              ? <p style={{ fontSize: 12, color: FADE }}>No activity yet.</p>
              : activity.map((a, i) => (
                <div key={i} style={{ display: "flex", gap: 8, fontSize: 12, padding: "5px 0", borderTop: i > 0 ? `1px solid rgba(255,255,255,0.05)` : "none" }}>
                  <span style={{ color: i === activity.length - 1 ? RED : INK }}>{i === activity.length - 1 ? "●" : "○"}</span>
                  <span>{a}</span>
                </div>
              ))
            }
          </div>

          {/* Approve / Decline */}
          {pending ? (
            <div className="approve-bar">
              <button onClick={() => handleApprove(true)} className="h-fill"
                style={{ flex: 1, background: "transparent", border: "none", borderRight: `1px solid ${INK}`, padding: "14px 0", fontSize: 11, letterSpacing: "0.08em", color: INK, cursor: "pointer" }}>
                APPROVE
              </button>
              <button onClick={() => handleApprove(false)}
                style={{ flex: 1, background: "transparent", border: "none", padding: "14px 0", fontSize: 11, letterSpacing: "0.08em", color: FADE, cursor: "pointer" }}>
                DECLINE
              </button>
            </div>
          ) : (
            <div className="approve-bar" style={{ alignItems: "center" }}>
              <button disabled style={{ flex: 1, background: "transparent", border: "none", padding: "14px 24px", fontSize: 11, letterSpacing: "0.08em", opacity: approved ? 0.4 : 0.25, color: INK, cursor: "default", textAlign: "center" }}>
                {approved ? "APPROVED" : "APPROVE ORDER"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Footer ── */}
      <div style={{ background: INK, color: BG, display: "flex", justifyContent: "space-between", padding: "10px 40px", fontSize: 10, letterSpacing: "0.06em", flexShrink: 0 }}>
        <span>BUILT WITH LANGGRAPH + SWIGGY MCP</span>
        <span>© SWIGGYPILOT · ALL ORDERS FINAL</span>
      </div>
    </div>
  );
}
