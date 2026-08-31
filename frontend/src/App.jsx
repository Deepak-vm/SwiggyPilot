import { useState, useRef, useEffect, useCallback } from "react";

const API   = "http://localhost:8000";
const BG    = "#121212";
const INK   = "#EDEAE0";
const RED   = "#FF5A3C";
const FADE  = "#8F8B80";
const GREEN = "#4ADE80";

export default function App() {
  const [messages,    setMessages]    = useState([]);
  const [activity,    setActivity]    = useState([]);
  const [input,       setInput]       = useState("");
  const [loading,     setLoading]     = useState(false);
  const [streaming,   setStreaming]   = useState(false);   // token-by-token mode
  const [threadId,    setThreadId]    = useState(null);
  const [pending,     setPending]     = useState(false);
  const [approved,    setApproved]    = useState(false);   // null | true | false
  const [menuOpen,    setMenuOpen]    = useState(false);
  const [orderNum,    setOrderNum]    = useState(null);
  const [itemCount,   setItemCount]   = useState(null);
  const [totalAmount, setTotalAmount] = useState(null);
  const [orderStatus, setOrderStatus] = useState(null);   // null | "placed" | "declined"
  const [orderId,     setOrderId]     = useState(null);

  const feedRef        = useRef(null);
  const streamBufRef   = useRef("");   // accumulates streamed tokens for current message
  const abortRef       = useRef(null); // AbortController for fetch

  // Auto-scroll feed
  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const pad    = (n) => String(n).padStart(2, "0");
  const addMsg = useCallback((who, text) =>
    setMessages(m => [...m, { n: pad(m.length + 1), who, text }]), []);
  const addLog = useCallback((text) =>
    setActivity(a => [...a, { text, ts: new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) }]), []);
  const patchLastMsg = (text) =>
    setMessages(m => m.map((msg, i) => i === m.length - 1 ? { ...msg, text } : msg));

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
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ message: msg, thread_id: threadId }),
        signal:  abort.signal,
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let   buf     = "";
      let   agentMsgAdded = false;

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
            if (!agentMsgAdded) {
              addMsg("AGENT", evt.content);
              agentMsgAdded = true;
              setStreaming(true);
            } else {
              streamBufRef.current += evt.content;
              patchLastMsg(streamBufRef.current);
            }
            streamBufRef.current += (agentMsgAdded && streamBufRef.current === "") ? evt.content : "";
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
            if (evt.item_count  != null) setItemCount(evt.item_count);
            if (evt.total_amount)        setTotalAmount(evt.total_amount);

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
          const res  = await fetch(`${API}/chat`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ message: msg, thread_id: threadId }),
          });
          const data = await res.json();
          addMsg("AGENT", data.reply || "—");
          if (!threadId && data.thread_id) {
            setThreadId(data.thread_id);
            setOrderNum(data.thread_id.slice(0, 8).toUpperCase());
          }
          if (data.item_count  != null) setItemCount(data.item_count);
          if (data.total_amount)        setTotalAmount(data.total_amount);
          if (data.intent)              addLog(`Intent: ${data.intent}`);
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
      const res  = await fetch(`${API}/approve`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ thread_id: threadId, approved: yes }),
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
            if (s.total_amount)    setTotalAmount(s.total_amount);
          } catch {}
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
    <div style={{ background: BG, height: "100vh", display: "flex", flexDirection: "column",
                  fontFamily: "'Inter',sans-serif", color: INK, overflow: "hidden" }}>
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
      `}</style>

      {/* ── Top bar ── */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center",
                    padding:"12px 40px", borderBottom:`1px solid ${INK}`, flexShrink:0 }}>
        <span style={{ fontSize:11, letterSpacing:"0.1em", color:FADE }}>SWIGGYPILOT</span>
        <div style={{ position:"relative" }}>
          <button onClick={() => setMenuOpen(v => !v)} aria-label="Account"
            style={{ width:32, height:32, borderRadius:"50%", border:`1px solid ${INK}`,
                     background: menuOpen ? INK : "transparent", color: menuOpen ? BG : INK,
                     fontSize:12, fontWeight:600, cursor:"pointer" }}>DK</button>
          {menuOpen && (
            <div style={{ position:"absolute", right:0, top:40, width:260,
                          background:BG, border:`1px solid ${INK}`, zIndex:20 }}>
              <div style={{ padding:"14px 18px", borderBottom:`1px solid ${INK}` }}>
                <div style={{ fontSize:13, fontWeight:600 }}>Deepak</div>
                <div style={{ fontSize:11, color:FADE, marginTop:2 }}>+91 9XXXX XXXXX · Swiggy linked</div>
              </div>
              <div style={{ padding:"12px 18px", borderBottom:`1px solid ${INK}` }}>
                <div style={{ fontSize:10, letterSpacing:"0.08em", color:FADE, marginBottom:8 }}>SAVED ADDRESSES</div>
                {[["HOME","B-12 Vaishali Nagar, Jaipur"],["WORK","JKLU Campus, Ajmer Road"]].map(([t,l],i) => (
                  <div key={i} style={{ display:"flex", justifyContent:"space-between", fontSize:12, padding:"4px 0" }}>
                    <span style={{ color:FADE, minWidth:44 }}>{t}</span><span style={{ textAlign:"right" }}>{l}</span>
                  </div>
                ))}
              </div>
              {["Past orders","Track a live order","Payment method · COD"].map((t,i) => (
                <button key={i} className="mrow"
                  style={{ width:"100%", textAlign:"left", background:"transparent", border:"none",
                           borderBottom:`1px solid ${INK}`, color:INK, padding:"10px 18px",
                           fontSize:12, cursor:"pointer" }}>{t}</button>
              ))}
              <button className="mrow"
                style={{ width:"100%", textAlign:"left", background:"transparent", border:"none",
                         color:RED, padding:"10px 18px", fontSize:12, cursor:"pointer" }}>Log out</button>
            </div>
          )}
        </div>
      </div>

      {/* ── Hero ── */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center",
                    padding:"16px 40px", flexShrink:0 }}>
        <h1 style={{ fontFamily:"'Anton',sans-serif", fontSize:52, lineHeight:1, textTransform:"uppercase" }}>
          JUST SAY <span style={{ color:RED }}>IT.</span>
        </h1>
        <p style={{ maxWidth:240, fontSize:12, lineHeight:1.6, color:FADE, textAlign:"right" }}>
          You type the request. SwiggyPilot finds it, carts it, and waits for your yes before anything is real.
        </p>
      </div>

      <div style={{ borderTop:`2px solid ${INK}`, flexShrink:0 }} />

      {/* ── Status bar ── */}
      <div style={{ padding:"10px 40px", borderBottom:`1px solid ${INK}`, fontSize:12,
                    flexShrink:0, display:"flex", alignItems:"center", gap:8 }}>
        {(loading || streaming) && (
          <span className="typing-dot" style={{ color:RED, fontSize:8 }}>●</span>
        )}
        {statusText}
      </div>

      {/* ── Main two-column ── */}
      <div style={{ display:"flex", flex:1, overflow:"hidden" }}>

        {/* Left: chat */}
        <div style={{ flex:"1 1 0", borderRight:`1px solid ${INK}`, display:"flex",
                      flexDirection:"column", overflow:"hidden" }}>
          <div ref={feedRef} style={{ flex:1, overflowY:"auto", padding:"20px 32px",
                                      display:"flex", flexDirection:"column", gap:16 }}>
            {messages.length === 0 && (
              <p style={{ color:FADE, fontSize:13 }}>Start by telling SwiggyPilot what you want.</p>
            )}
            {messages.map((m, i) => (
              <div key={i} style={{ display:"flex", gap:12 }}>
                <span style={{ fontSize:11, color:FADE, paddingTop:2, minWidth:20, flexShrink:0 }}>{m.n}</span>
                <div>
                  <div style={{ fontSize:10, letterSpacing:"0.08em",
                                color: m.who === "YOU" ? FADE : RED,
                                marginBottom:2, fontWeight:600 }}>{m.who}</div>
                  <p style={{ margin:0, fontSize:14, lineHeight:1.55, whiteSpace:"pre-wrap" }}>{m.text}</p>
                </div>
              </div>
            ))}
            {loading && !streaming && (
              <div style={{ display:"flex", gap:12 }}>
                <span style={{ fontSize:11, color:FADE, paddingTop:2, minWidth:20 }}>{pad(messages.length + 1)}</span>
                <div>
                  <div style={{ fontSize:10, letterSpacing:"0.08em", color:RED, marginBottom:2, fontWeight:600 }}>AGENT</div>
                  <p style={{ margin:0, fontSize:14, color:FADE }}>
                    <span className="typing-dot">•</span>
                    <span className="typing-dot" style={{ animationDelay:"0.2s" }}>•</span>
                    <span className="typing-dot" style={{ animationDelay:"0.4s" }}>•</span>
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
              style={{ flex:1, background:"transparent", border:"none",
                       padding:"14px 32px", fontSize:14, color:INK }} />
            <button onClick={send} disabled={loading} className="h-new"
              style={{ background:BG, color:INK, border:"none", padding:"0 28px",
                       borderLeft:"1px solid #3A362E", fontSize:11, letterSpacing:"0.08em",
                       cursor:"pointer", flexShrink:0 }}>SEND</button>
            <button onClick={reset} className="h-new"
              style={{ background:BG, color:INK, border:"none", padding:"0 28px",
                       borderLeft:"1px solid #3A362E", fontSize:11, letterSpacing:"0.08em",
                       cursor:"pointer", flexShrink:0 }}>NEW ORDER</button>
          </div>
        </div>

        {/* Right: order panel */}
        <div style={{ width:340, flexShrink:0, display:"flex", flexDirection:"column", overflow:"hidden" }}>
          {/* Panel header */}
          <div style={{ display:"flex", justifyContent:"space-between", padding:"12px 24px",
                        borderBottom:`1px solid ${INK}`, fontSize:10, letterSpacing:"0.08em",
                        color:FADE, flexShrink:0 }}>
            <span>CURRENT ORDER</span>
            <span>{orderNum ? `ORDER #${orderNum}` : "—"}</span>
          </div>

          {/* Items + Total */}
          <div style={{ display:"flex", borderBottom:`1px solid ${INK}`, flexShrink:0 }}>
            <div style={{ flex:1, padding:"16px 24px", borderRight:`1px solid ${INK}` }}>
              <div style={{ fontSize:10, letterSpacing:"0.08em", color:FADE, marginBottom:4 }}>ITEMS</div>
              <div style={{ fontFamily:"'Anton',sans-serif", fontSize:40, lineHeight:1 }}>
                {itemCount != null ? itemCount : "—"}
              </div>
            </div>
            <div style={{ flex:1, padding:"16px 24px" }}>
              <div style={{ fontSize:10, letterSpacing:"0.08em", color:FADE, marginBottom:4 }}>TOTAL · COD</div>
              <div style={{ fontFamily:"'Anton',sans-serif", fontSize:totalAmount && totalAmount.length > 5 ? 28 : 40,
                            lineHeight:1, color:RED }}>
                {totalAmount || "—"}
              </div>
            </div>
          </div>

          {/* Activity log */}
          <div style={{ flex:1, overflowY:"auto", padding:"16px 24px", borderBottom:`1px solid ${INK}` }}>
            <div style={{ fontSize:10, letterSpacing:"0.08em", color:FADE, marginBottom:10 }}>
              ACTIVITY LOG &nbsp;·&nbsp; {activity.length} updates
            </div>
            {activity.length === 0
              ? <p style={{ fontSize:12, color:FADE }}>No activity yet.</p>
              : activity.map((a, i) => (
                <div key={i} style={{ display:"flex", gap:8, fontSize:12, padding:"5px 0",
                                      borderTop: i > 0 ? `1px solid rgba(255,255,255,0.05)` : "none" }}>
                  <span style={{ color: i === activity.length - 1 ? RED : FADE, flexShrink:0 }}>
                    {i === activity.length - 1 ? "●" : "○"}
                  </span>
                  <span style={{ flex:1 }}>{a.text}</span>
                  {a.ts && <span style={{ color:FADE, fontSize:10, flexShrink:0 }}>{a.ts}</span>}
                </div>
              ))
            }
          </div>

          {/* Approve / Decline */}
          {pending ? (
            <div className="approve-bar">
              <button onClick={() => handleApprove(true)} className="h-fill"
                style={{ flex:1, background:"transparent", border:"none",
                         borderRight:`1px solid ${INK}`, padding:"14px 0",
                         fontSize:11, letterSpacing:"0.08em", color:INK, cursor:"pointer" }}>
                APPROVE
              </button>
              <button onClick={() => handleApprove(false)}
                style={{ flex:1, background:"transparent", border:"none",
                         padding:"14px 0", fontSize:11, letterSpacing:"0.08em",
                         color:FADE, cursor:"pointer" }}>
                DECLINE
              </button>
            </div>
          ) : (
            <div className="approve-bar" style={{ alignItems:"center" }}>
              <button disabled style={{
                flex:1, background:"transparent", border:"none", padding:"14px 24px",
                fontSize:11, letterSpacing:"0.08em", cursor:"default", textAlign:"center",
                color: orderStatus === "placed" ? GREEN : orderStatus === "declined" ? RED : INK,
                opacity: orderStatus ? 1 : 0.25,
              }}>
                {orderStatus === "placed"
                  ? `PLACED${orderId ? ` · ${orderId.slice(0,8)}` : ""}`
                  : orderStatus === "declined"
                  ? "DECLINED"
                  : "APPROVE ORDER"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Footer ── */}
      <div style={{ background:INK, color:BG, display:"flex", justifyContent:"space-between",
                    padding:"10px 40px", fontSize:10, letterSpacing:"0.06em", flexShrink:0 }}>
        <span>BUILT WITH LANGGRAPH + SWIGGY MCP</span>
        <span>© SWIGGYPILOT · ALL ORDERS FINAL</span>
      </div>
    </div>
  );
}
