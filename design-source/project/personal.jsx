// Personal AI chat view — 1:1 with Donna, with chat history sidebar
function PersonalView({ currentAgent, setCurrentAgent }) {
  const d = window.DONNA_DATA;
  const agent = window.lookup(currentAgent);

  return (
    <div className="personal">
      {/* History sidebar */}
      <aside className="hist">
        <div className="new-chat">
          <Ic.plus/>
          <span>New chat with Donna</span>
        </div>
        <div className="htag">Today</div>
        {d.personalChats.filter(c => c.when === "Today").map(c => (
          <PersonalHistItem key={c.id} chat={c} active={c.id === "p1"}/>
        ))}
        <div className="htag">Earlier</div>
        {d.personalChats.filter(c => c.when !== "Today").map(c => (
          <PersonalHistItem key={c.id} chat={c}/>
        ))}
        <div style={{ padding: "10px 12px 0", fontSize: 11.5, color: "var(--text-3)", borderTop: "1px solid var(--border)", marginTop: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Ic.archive/>
            <span>Archived chats (38)</span>
          </div>
        </div>
      </aside>

      {/* Chat */}
      <div className="chat">
        <div className="chat-head">
          <Av kind="agent" agent={agent} size="lg" pulsing/>
          <div>
            <div className="who">Donna</div>
            <div className="role">Your Chief of Staff · Private chat, end-to-end</div>
          </div>
          <div className="spacer"/>
          <button className="pill" style={{
            display: "flex", alignItems: "center", gap: 6,
            height: 28, padding: "0 12px", borderRadius: 7,
            border: "1px solid var(--border)", background: "var(--bg-2)",
            fontSize: 12, color: "var(--text-1)"
          }}>
            <Ic.brain/> Memory · 142 items
          </button>
          <button className="pill" style={{
            display: "flex", alignItems: "center", gap: 6,
            height: 28, padding: "0 12px", borderRadius: 7,
            border: "1px solid var(--border)", background: "var(--bg-2)",
            fontSize: 12, color: "var(--text-1)"
          }}>
            Switch agent <Ic.caret/>
          </button>
        </div>
        <div className="chat-body">
          <div style={{ alignSelf: "center", color: "var(--text-3)", fontSize: 11.5, letterSpacing: 0.4, textTransform: "uppercase" }}>Today · 9:14 AM</div>
          {d.personalMessages.map(m => <PersonalMsg key={m.id} msg={m}/>)}
        </div>
        <div className="composer" style={{ margin: "0 22px 18px" }}>
          <div className="input">
            <span className="placeholder">Ask Donna anything · drop a file · /command</span>
          </div>
          <div className="footer">
            <button className="btn-i"><Ic.plus/></button>
            <button className="btn-i"><Ic.at/></button>
            <button className="btn-i"><Ic.smile/></button>
            <div className="at-agents"><Ic.brain/>Memory on</div>
            <span className="spacer"/>
            <button className="send"><Ic.send/></button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PersonalHistItem({ chat, active }) {
  const agent = window.lookup(chat.agent);
  return (
    <div className={"h-item " + (active ? "active" : "")}>
      <div className="htitle">{chat.title}</div>
      <div className="hprev">{chat.preview}</div>
      <div className="hmeta">
        <Av kind="agent" agent={agent} size="sm"/>
        <span>{agent.name}</span>
        <span style={{ marginLeft: "auto" }}>{chat.when}</span>
      </div>
    </div>
  );
}

function PersonalMsg({ msg }) {
  if (msg.role === "you") {
    return <div className="bubble user">{msg.text}</div>;
  }
  const agent = window.lookup(msg.agent);
  return (
    <div className="bubble agent">
      <Av kind="agent" agent={agent} pulsing={msg.streaming}/>
      <div style={{ flex: 1 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "baseline", marginBottom: 2 }}>
          <span style={{ fontWeight: 600, color: "var(--text-0)", fontSize: 13.5 }}>Donna</span>
          <span style={{ fontSize: 11, color: "var(--text-3)" }}>{msg.time}</span>
        </div>
        {msg.streaming && msg.currentThought && (
          <div className="run-thought" style={{ marginBottom: 6 }}>
            <span style={{ flex: 1 }}>{msg.currentThought}<span className="dots"/></span>
          </div>
        )}
        {msg.text && <div className="text">{msg.text}</div>}
        {msg.attachments && (
          <div className="attachments" style={{ marginTop: 8 }}>
            {msg.attachments.map((a, i) => (
              <div key={i} className="attach">
                <span className="icon"><Ic.file/></span>
                <span className="name">{a.name}</span>
                <span className="size">{a.size}</span>
              </div>
            ))}
          </div>
        )}
        {msg.text && (
          <div style={{ display: "flex", gap: 6, marginTop: 8, fontSize: 11.5, color: "var(--text-3)" }}>
            <button style={{ color: "var(--text-3)" }}>↻ Regenerate</button>
            <span>·</span>
            <button style={{ color: "var(--text-3)" }}>📌 Pin</button>
            <span>·</span>
            <button style={{ color: "var(--ai-dim)" }}>✦ Promote to channel</button>
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { PersonalView });
