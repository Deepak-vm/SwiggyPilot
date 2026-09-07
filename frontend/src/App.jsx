import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";

const API = "http://localhost:8000";
const BG = "#121212";
const INK = "#EDEAE0";
const RED = "#FF5A3C";
const FADE = "#8F8B80";
const GREEN = "#4ADE80";

// ── localStorage helpers ──────────────────────────────────────────────────
const LS_KEY = "swiggypilot_session";
const loadSession = () => {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) ?? {}; } catch { return {}; }
};

export default function App() {
  const [messages, setMessages] = useState(() => loadSession().messages ?? []);
  const [activity, setActivity] = useState(() => loadSession().activity ?? []);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);   // token-by-token mode
  const [threadId, setThreadId] = useState(() => loadSession().threadId ?? null);
  const [pending, setPending] = useState(() => loadSession().pending ?? false);
  const [approved, setApproved] = useState(() => loadSession().approved ?? false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [orderNum, setOrderNum] = useState(() => loadSession().orderNum ?? null);
  const [itemCount, setItemCount] = useState(() => loadSession().itemCount ?? null);
  const [totalAmount, setTotalAmount] = useState(() => loadSession().totalAmount ?? null);
  const [orderStatus, setOrderStatus] = useState(() => loadSession().orderStatus ?? null);
  const [orderId, setOrderId] = useState(() => loadSession().orderId ?? null);

  const feedRef = useRef(null);
  const streamBufRef = useRef("");   // accumulates streamed tokens for current message
  const abortRef = useRef(null); // AbortController for fetch

  // Persist session to localStorage whenever relevant state changes
  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({
        messages, activity, threadId, pending, approved,
        orderNum, itemCount, totalAmount, orderStatus, orderId,
      }));
    } catch { }
  }, [messages, activity, threadId, pending, approved, orderNum, itemCount, totalAmount, orderStatus, orderId]);

  // Auto-scroll feed
  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const pad = (n) => String(n).padStart(2, "0");

  // Normalise content that may arrive as a string OR as an Anthropic block {type,text,index}
  const toText = (content) => {
    if (typeof content === "string") return content;
    if (content && typeof content === "object") {
      if (typeof content.text === "string") return content.text;
      // Array of content blocks
      if (Array.isArray(content)) return content.map(toText).join("");
    }
    return String(content ?? "");
  };

  const addMsg = useCallback((who, text) =>
    setMessages(m => [...m, { n: pad(m.length + 1), who, text: toText(text) }]), []);
  const addLog = useCallback((text) =>
    setActivity(a => [...a, { text: toText(text), ts: new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) }]), []);
  const patchLastMsg = (text) =>
    setMessages(m => m.map((msg, i) => i === m.length - 1 ? { ...msg, text: toText(text) } : msg));

  // ── SEND (SSE streaming) ──────────────────────────────────────────────────
  const send = async () => {
    const msg = input.trim();
    if (!msg || loading) return;
    setInput("");
    addMsg("YOU", msg);
    setLoading(true);
    setStreaming(false);
    streamBufRef.current = "";

    const abort = new AbortController();
    abortRef.current = abort;
    addLog("Sending to agent…");

    try {
      const res = await fetch(`${API}/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, thread_id: threadId }),
        signal: abort.signal,
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let agentMsgAdded = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop(); // keep incomplete line

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          let evt;
          try { evt = JSON.parse(raw); } catch { continue; }

          if (evt.type === "token") {
            const tokenText = toText(evt.content);
            if (!agentMsgAdded) {
              addMsg("AGENT", tokenText);
              streamBufRef.current = tokenText;
              agentMsgAdded = true;
              setStreaming(true);
            } else {
              streamBufRef.current += tokenText;
              patchLastMsg(streamBufRef.current);
            }
          }

          else if (evt.type === "log") {
            addLog(evt.content);
          }

          else if (evt.type === "done") {
            setStreaming(false);
            const newThreadId = evt.thread_id;

            // Finalise the streamed message or add a new one
            if (evt.reply) {
              if (!agentMsgAdded) {
                addMsg("AGENT", evt.reply);
              } else {
                patchLastMsg(evt.reply);
              }
            }

            // Thread + order panel
            if (!threadId && newThreadId) {
              setThreadId(newThreadId);
              setOrderNum(newThreadId.slice(0, 8).toUpperCase());
            }
            if (evt.item_count != null) setItemCount(evt.item_count);
            if (evt.total_amount) setTotalAmount(evt.total_amount);

            // Activity log — intent
            if (evt.intent) addLog(`Intent: ${evt.intent}`);

            if (evt.pending_approval) {
              setPending(true);
              addLog("Cart ready — awaiting your approval");
            } else {
              addLog(`Agent replied · step ${pad(messages.length + 2)}`);
            }
          }

          else if (evt.type === "error") {
            addMsg("AGENT", `Error: ${evt.content}`);
            addLog("Agent error — see message");
            setStreaming(false);
          }
        }
      }

    } catch (err) {
      if (err.name !== "AbortError") {
        // Fallback to non-streaming /chat
        try {
          addLog("Streaming failed, falling back to /chat…");
          const res = await fetch(`${API}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: msg, thread_id: threadId }),
          });
          const data = await res.json();
          addMsg("AGENT", data.reply || "—");
          if (!threadId && data.thread_id) {
            setThreadId(data.thread_id);
            setOrderNum(data.thread_id.slice(0, 8).toUpperCase());
          }
          if (data.item_count != null) setItemCount(data.item_count);
          if (data.total_amount) setTotalAmount(data.total_amount);
          if (data.intent) addLog(`Intent: ${data.intent}`);
          if (data.pending_approval) {
            setPending(true);
            addLog("Cart ready — awaiting your approval");
          }
        } catch {
          addMsg("AGENT", "Connection error. Is the backend running?");
          addLog("Connection failed");
        }
      }
    }

    setLoading(false);
  };

  // ── APPROVE / DECLINE ─────────────────────────────────────────────────────
  const handleApprove = async (yes) => {
    setPending(false);
    setApproved(yes);
    setLoading(true);
    addLog(yes ? "Approving order…" : "Declining order…");

    try {
      const res = await fetch(`${API}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, approved: yes }),
      });
      const data = await res.json();

      addMsg("AGENT", data.reply || (yes ? "Order placed!" : "Order cancelled."));

      if (yes) {
        setOrderStatus("placed");
        if (data.swiggy_order_id) setOrderId(data.swiggy_order_id);
        addLog("Order placed successfully");
        // Poll /status once after 3s for final order ID
        setTimeout(async () => {
          try {
            const s = await fetch(`${API}/status/${threadId}`).then(r => r.json());
            if (s.swiggy_order_id) setOrderId(s.swiggy_order_id);
            if (s.total_amount) setTotalAmount(s.total_amount);
          } catch { }
        }, 3000);
      } else {
        setOrderStatus("declined");
        addLog("Order declined");
      }
    } catch {
      addMsg("AGENT", "Something went wrong.");
      addLog("Approval request failed");
    }

    setLoading(false);
  };

  // ── RESET ─────────────────────────────────────────────────────────────────
  const reset = () => {
    abortRef.current?.abort();
    localStorage.removeItem(LS_KEY);
    setMessages([]); setActivity([]);
    setThreadId(null); setOrderNum(null);
    setPending(false); setApproved(false);
    setItemCount(null); setTotalAmount(null);
    setOrderStatus(null); setOrderId(null);
    setStreaming(false); setLoading(false);
    streamBufRef.current = "";
  };

  // ── STATUS BAR TEXT ───────────────────────────────────────────────────────
  const statusText = streaming
    ? "Agent is responding…"
    : loading
      ? "Agent is thinking…"
      : pending
        ? "Waiting for your approval — nothing placed yet."
        : orderStatus === "placed"
          ? `Order placed${orderId ? ` · ID ${orderId}` : ""}`
          : orderStatus === "declined"
            ? "Order declined."
            : "No apps opened. No menus scrolled. Just this.";

  return (
    <div style={{
      background: BG, height: "100vh", display: "flex", flexDirection: "column",
      fontFamily: "'Inter',sans-serif", color: INK, overflow: "hidden"
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;500;600;700&display=swap');
        * { box-sizing:border-box; margin:0; }
        .h-fill:hover  { background:${INK}!important; color:${BG}!important; }
        .mrow:hover    { background:rgba(237,234,224,0.08); }
        input::placeholder { color:${FADE}; }
        input:focus, button:focus-visible { outline:2px solid ${INK}; outline-offset:2px; }
        ::-webkit-scrollbar { width:3px; } ::-webkit-scrollbar-thumb { background:${FADE}; }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
        .typing-dot { animation: blink 1s infinite; }

        /* ── Markdown rendering for agent messages ── */
        .md-body { font-size:14px; line-height:1.6; color:${INK}; }
        .md-body p  { margin:0 0 6px; }
        .md-body p:last-child { margin-bottom:0; }
        .md-body strong { color:${INK}; font-weight:600; }
        .md-body em     { opacity:0.85; }
        .md-body hr     { border:none; border-top:1px solid rgba(237,234,224,0.2); margin:8px 0; }
        .md-body ul, .md-body ol { padding-left:18px; margin:4px 0; }
        .md-body li { margin:2px 0; }
        .md-body code {
          background:rgba(237,234,224,0.1); border-radius:3px;
          padding:1px 5px; font-size:12px; font-family:monospace;
        }
        .md-body pre  { background:rgba(237,234,224,0.08); border-radius:4px; padding:8px 10px; overflow-x:auto; margin:6px 0; }
        .md-body pre code { background:none; padding:0; }
        .md-body table {
          border-collapse:collapse; width:100%; margin:8px 0; font-size:13px;
        }
        .md-body th, .md-body td {
          border:1px solid rgba(237,234,224,0.25);
          padding:5px 10px; text-align:left;
        }
        .md-body th {
          background:rgba(237,234,224,0.08); font-weight:600;
          font-size:11px; letter-spacing:0.05em; text-transform:uppercase;
        }
        .md-body tr:hover td { background:rgba(237,234,224,0.04); }
      `}</style>


      {/* ── Hero ── */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "16px 40px", flexShrink: 0
      }}>
        <h1 style={{ fontFamily: "'Anton',sans-serif", fontSize: 52, lineHeight: 1, textTransform: "uppercase" }}>
          JUST SAY <span style={{ color: RED }}>IT.</span>
        </h1>
        <p style={{ maxWidth: 240, fontSize: 12, lineHeight: 1.6, color: FADE, textAlign: "right" }}>
          You type the request. SwiggyPilot finds it, carts it, and waits for your yes before anything is real.
        </p>
      </div>

      <div style={{ borderTop: `2px solid ${INK}`, flexShrink: 0 }} />

      {/* ── Status bar ── */}
      <div style={{
        padding: "10px 40px", borderBottom: `1px solid ${INK}`, fontSize: 12,
        flexShrink: 0, display: "flex", alignItems: "center", gap: 8
      }}>
        {(loading || streaming) && (
          <span className="typing-dot" style={{ color: RED, fontSize: 8 }}>●</span>
        )}
        {statusText}
      </div>

      {/* ── Main two-column ── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* Left: chat */}
        <div style={{
          flex: "1 1 0", borderRight: `1px solid ${INK}`, display: "flex",
          flexDirection: "column", overflow: "hidden"
        }}>
          <div ref={feedRef} style={{
            flex: 1, overflowY: "auto", padding: "20px 32px",
            display: "flex", flexDirection: "column", gap: 16
          }}>
            {messages.length === 0 && (
              <p style={{ color: FADE, fontSize: 13 }}>Start by telling SwiggyPilot what you want.</p>
            )}
            {messages.map((m, i) => (
              <div key={i} style={{ display: "flex", gap: 12 }}>
                <span style={{ fontSize: 11, color: FADE, paddingTop: 2, minWidth: 20, flexShrink: 0 }}>{m.n}</span>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{
                    fontSize: 10, letterSpacing: "0.08em",
                    color: m.who === "YOU" ? FADE : RED,
                    marginBottom: 4, fontWeight: 600
                  }}>{m.who}</div>
                  {m.who === "AGENT" ? (
                    <div className="md-body">
                      <ReactMarkdown>{m.text}</ReactMarkdown>
                    </div>
                  ) : (
                    <p style={{ margin: 0, fontSize: 14, lineHeight: 1.55, whiteSpace: "pre-wrap" }}>{m.text}</p>
                  )}
                </div>
              </div>
            ))}
            {loading && !streaming && (
              <div style={{ display: "flex", gap: 12 }}>
                <span style={{ fontSize: 11, color: FADE, paddingTop: 2, minWidth: 20 }}>{pad(messages.length + 1)}</span>
                <div>
                  <div style={{ fontSize: 10, letterSpacing: "0.08em", color: RED, marginBottom: 2, fontWeight: 600 }}>AGENT</div>
                  <p style={{ margin: 0, fontSize: 14, color: FADE }}>
                    <span className="typing-dot">•</span>
                    <span className="typing-dot" style={{ animationDelay: "0.2s" }}>•</span>
                    <span className="typing-dot" style={{ animationDelay: "0.4s" }}>•</span>
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Input + actions row */}
          <div className="bottom-bar">
            <input value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && send()}
              placeholder="Tell it what you need"
              style={{
                flex: 1, background: "transparent", border: "none",
                padding: "14px 32px", fontSize: 14, color: INK
              }} />
            <button onClick={send} disabled={loading} className="h-new"
              style={{
                background: BG, color: INK, border: "none", padding: "0 28px",
                borderLeft: "1px solid #3A362E", fontSize: 11, letterSpacing: "0.08em",
                cursor: "pointer", flexShrink: 0
              }}>SEND</button>
            <button onClick={reset} className="h-new"
              style={{
                background: BG, color: INK, border: "none", padding: "0 28px",
                borderLeft: "1px solid #3A362E", fontSize: 11, letterSpacing: "0.08em",
                cursor: "pointer", flexShrink: 0
              }}>NEW ORDER</button>
          </div>
        </div>

        {/* Right: order panel */}
        <div style={{ width: 340, flexShrink: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Panel header */}
          <div style={{
            display: "flex", justifyContent: "space-between", padding: "12px 24px",
            borderBottom: `1px solid ${INK}`, fontSize: 10, letterSpacing: "0.08em",
            color: FADE, flexShrink: 0
          }}>
            <span>CURRENT ORDER</span>
            <span>{orderNum ? `ORDER #${orderNum}` : "—"}</span>
          </div>

          {/* Items + Total */}
          <div style={{ display: "flex", borderBottom: `1px solid ${INK}`, flexShrink: 0 }}>
            <div style={{ flex: 1, padding: "16px 24px", borderRight: `1px solid ${INK}` }}>
              <div style={{ fontSize: 10, letterSpacing: "0.08em", color: FADE, marginBottom: 4 }}>ITEMS</div>
              <div style={{ fontFamily: "'Anton',sans-serif", fontSize: 40, lineHeight: 1 }}>
                {itemCount != null ? itemCount : "—"}
              </div>
            </div>
            <div style={{ flex: 1, padding: "16px 24px" }}>
              <div style={{ fontSize: 10, letterSpacing: "0.08em", color: FADE, marginBottom: 4 }}>TOTAL · COD</div>
              <div style={{
                fontFamily: "'Anton',sans-serif", fontSize: totalAmount && totalAmount.length > 5 ? 28 : 40,
                lineHeight: 1, color: RED
              }}>
                {totalAmount || "—"}
              </div>
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
                <div key={i} style={{
                  display: "flex", gap: 8, fontSize: 12, padding: "5px 0",
                  borderTop: i > 0 ? `1px solid rgba(255,255,255,0.05)` : "none"
                }}>
                  <span style={{ color: i === activity.length - 1 ? RED : FADE, flexShrink: 0 }}>
                    {i === activity.length - 1 ? "●" : "○"}
                  </span>
                  <span style={{ flex: 1 }}>{a.text}</span>
                  {a.ts && <span style={{ color: FADE, fontSize: 10, flexShrink: 0 }}>{a.ts}</span>}
                </div>
              ))
            }
          </div>

          {/* Approve / Decline */}
          {pending ? (
            <div className="approve-bar">
              <button onClick={() => handleApprove(true)} className="h-fill"
                style={{
                  flex: 1, background: "transparent", border: "none",
                  borderRight: `1px solid ${INK}`, padding: "14px 0",
                  fontSize: 11, letterSpacing: "0.08em", color: INK, cursor: "pointer"
                }}>
                APPROVE
              </button>
              <button onClick={() => handleApprove(false)}
                style={{
                  flex: 1, background: "transparent", border: "none",
                  padding: "14px 0", fontSize: 11, letterSpacing: "0.08em",
                  color: FADE, cursor: "pointer"
                }}>
                DECLINE
              </button>
            </div>
          ) : (
            <div className="approve-bar" style={{ alignItems: "center" }}>
              <button disabled style={{
                flex: 1, background: "transparent", border: "none", padding: "14px 24px",
                fontSize: 11, letterSpacing: "0.08em", cursor: "default", textAlign: "center",
                color: orderStatus === "placed" ? GREEN : orderStatus === "declined" ? RED : INK,
                opacity: orderStatus ? 1 : 0.25,
              }}>
                {orderStatus === "placed"
                  ? `PLACED${orderId ? ` · ${orderId.slice(0, 8)}` : ""}`
                  : orderStatus === "declined"
                    ? "DECLINED"
                    : "APPROVE ORDER"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Footer ── */}
      <div style={{
        background: INK, color: BG, display: "flex", justifyContent: "space-between",
        padding: "10px 40px", fontSize: 10, letterSpacing: "0.06em", flexShrink: 0
      }}>
        <span>BUILT WITH LANGGRAPH + SWIGGY MCP</span>
        <span>© SWIGGYPILOT · ALL ORDERS FINAL</span>
      </div>
    </div>
  );
}
