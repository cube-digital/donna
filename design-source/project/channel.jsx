// Channel view — the centerpiece. Mixed human + AI messages.
// Agent runs are first-class objects with steps, streaming state, memory.

function AgentRunCard({ msg }) {
  const agent = window.lookup(msg.author);
  const [expanded, setExpanded] = React.useState(true);
  return (
    <div className="run">
      <div className="run-head">
        <span className="label">Agent run</span>
        <span style={{ color: "var(--text-3)" }}>·</span>
        <span className="summary">{msg.summary}</span>
        <span className="spacer"/>
        <span className="status">
          <span className={"led " + msg.status}/>
          {msg.status === "running" ? "Running" : "Completed"}
        </span>
        <button className="toggle" onClick={() => setExpanded(e => !e)}>{expanded ? "Hide steps" : "Show steps"}</button>
      </div>
      {expanded && (
        <div className="run-body">
          {msg.streaming && msg.currentThought && (
            <div className="run-thought">
              <span style={{ flex: 1 }}>{msg.currentThought}<span className="dots"/></span>
            </div>
          )}
          <div className="run-steps">
            {msg.steps.map((s, i) => <RunStep key={i} step={s} />)}
          </div>
          {msg.output && (
            <div className="run-output">{msg.output}</div>
          )}
          {msg.attachments && msg.attachments.map((a, i) => (
            <div key={i} className="attach" style={{ marginTop: 8 }}>
              <span className="icon"><Ic.link/></span>
              <span className="name">{a.name}</span>
              <span className="size">{a.size}</span>
            </div>
          ))}
        </div>
      )}
      {msg.memoryTouched && (
        <div className="run-foot">
          <span style={{ fontSize: 11, color: "var(--text-3)", letterSpacing: 0.4, textTransform: "uppercase" }}>Memory used</span>
          {msg.memoryTouched.map((m, i) => (
            <span key={i} className="mem"><Ic.brain/>{m}</span>
          ))}
          <span className="spacer"/>
          <button className="act">Add to context</button>
          <button className="act primary">Continue with {agent.name}</button>
        </div>
      )}
    </div>
  );
}

function RunStep({ step }) {
  const icon = {
    read: <Ic.doc/>, write: <Ic.edit/>, think: <Ic.brain/>, tool: <Ic.bolt/>,
  }[step.kind] || <Ic.bolt/>;
  return (
    <div className="run-step">
      <div className="step-icon">{icon}</div>
      <span className="label">{step.label}</span>
      {step.meta && <span className="meta">{step.meta}</span>}
      {step.state && (
        <span className={"state " + step.state}>
          <span className="led"/>{step.state}
        </span>
      )}
    </div>
  );
}

function Message({ msg }) {
  if (msg.kind === "system") {
    return <div className="msg system">{msg.text}</div>;
  }
  const author = window.lookup(msg.author);
  const isAgent = author.kind === "agent";

  return (
    <div className="msg">
      <div className="av-col">
        <Av kind={author.kind} who={author} agent={author} pulsing={msg.kind === "agent-run" && msg.status === "running"}/>
      </div>
      <div className="body">
        <div className="head">
          <span className={"who " + (isAgent ? "agent" : "")}>{author.name}</span>
          {isAgent && <span className="role-chip">Agent</span>}
          <span className="time">{msg.time}</span>
        </div>
        {msg.kind === "msg" && (
          <>
            <div className="text">{msg.text}</div>
            {msg.attachments && (
              <div className="attachments">
                {msg.attachments.map((a, i) => (
                  <div key={i} className="attach">
                    <span className="icon"><Ic.file/></span>
                    <span className="name">{a.name}</span>
                    <span className="size">{a.size}</span>
                  </div>
                ))}
              </div>
            )}
            {msg.reactions && (
              <div className="reactions">
                {msg.reactions.map((r, i) => (
                  <button key={i} className="react"><span>{r.emoji}</span><span className="count">{r.count}</span></button>
                ))}
                <button className="react" style={{ background: "transparent", borderStyle: "dashed", color: "var(--text-3)" }}>
                  <Ic.smile/>
                </button>
              </div>
            )}
          </>
        )}
        {msg.kind === "agent-run" && <AgentRunCard msg={msg}/>}
      </div>
      <div className="hover-actions">
        <button className="hb" title="React"><Ic.smile/></button>
        <button className="hb" title="Reply in thread"><Ic.thread/></button>
        <button className="hb" title="Share"><Ic.share/></button>
        <button className="hb ai" title="Ask an agent"><Ic.sparkle/></button>
        <button className="hb" title="More"><Ic.more/></button>
      </div>
    </div>
  );
}

function ChannelView({ channel }) {
  const d = window.DONNA_DATA;
  const scrollRef = React.useRef(null);

  React.useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, []);

  return (
    <div className="main-flex" style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <ChannelHeader channel={channel}/>
      <div ref={scrollRef} className="chat-scroll">
        <div className="day-divider"><span>Today · Apr 11</span></div>
        {d.channelMessages.map(m => <Message key={m.id} msg={m}/>)}
      </div>
      <Composer channel={channel}/>
    </div>
  );
}

function ChannelHeader({ channel }) {
  const d = window.DONNA_DATA;
  const agents = ["donna", "mira", "kai"];
  return (
    <header className="channel-header">
      <div>
        <div className="title">
          <Ic.hash/>
          <span>{channel}</span>
          <button style={{ color: "var(--text-3)" }}><Ic.star/></button>
        </div>
        <div className="meta">12 members · 3 AI teammates · Pinned: protocol v3, taxonomy</div>
      </div>
      <div className="spacer"/>
      <div className="pill ai" title="AI teammates in channel">
        <Ic.sparkle/>
        <div style={{ display: "flex", marginLeft: 2 }}>
          {agents.map(id => {
            const a = window.lookup(id);
            return <Av key={id} kind="agent" agent={a} size="sm" />;
          })}
        </div>
        <span style={{ marginLeft: 4 }}>3</span>
      </div>
      <div className="members">
        <div className="stack">
          {d.humans.slice(0, 4).map(h => (
            <Av key={h.id} kind="human" who={h} size="sm"/>
          ))}
        </div>
        <span className="count">12</span>
      </div>
      <button className="pill"><Ic.bell/> Notifications</button>
    </header>
  );
}

function Composer({ channel }) {
  const [text, setText] = React.useState("");
  const ready = text.trim().length > 0;
  return (
    <div className="composer">
      <div className="formatting">
        <button className="fmt-btn" title="Bold"><b>B</b></button>
        <button className="fmt-btn" title="Italic"><i>I</i></button>
        <button className="fmt-btn" title="Strike"><s>S</s></button>
        <span className="div"/>
        <button className="fmt-btn" title="Code"><span style={{ fontFamily: "Geist Mono", fontSize: 11 }}>{"</>"}</span></button>
        <button className="fmt-btn" title="Quote">"</button>
        <button className="fmt-btn" title="Link"><Ic.link/></button>
        <span className="div"/>
        <button className="fmt-btn" title="List">≡</button>
      </div>
      <div className="input">
        {text ? text : <span className="placeholder">Message #{channel} — type @donna or /agent to invoke a teammate</span>}
      </div>
      <div className="footer">
        <button className="btn-i"><Ic.plus/></button>
        <button className="btn-i"><Ic.at/></button>
        <button className="btn-i"><Ic.smile/></button>
        <div className="at-agents"><Ic.sparkle/>Agents on standby</div>
        <span className="spacer"/>
        <button className={"send " + (ready ? "ready" : "")}><Ic.send/></button>
      </div>
    </div>
  );
}

Object.assign(window, { ChannelView, Message, AgentRunCard });
