// Main App — view router + global state + tweaks
const { useState, useEffect } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "dark": true,
  "density": "comfortable",
  "agentHue": 282,
  "showArchive": true
}/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [view, setView] = useState("channel"); // channel | personal | search | profile | workspace | empty
  const [channel, setChannel] = useState("recist-protocol");
  const [currentAgent, setCurrentAgent] = useState("donna");
  const [vaultOpen, setVaultOpen] = useState(false);

  useEffect(() => {
    document.documentElement.style.setProperty("--ai-h", t.agentHue);
    if (t.dark) {
      document.body.classList.remove("theme-light");
    } else {
      document.body.classList.add("theme-light");
    }
  }, [t.dark, t.agentHue]);

  // Showcase script: cycle through views every 8s only on first paint? No — let user drive.

  const showRightRail = view !== "search" && view !== "empty";
  // Actually show right rail in empty too for suggestions
  const rrViews = ["channel", "personal", "profile", "workspace", "empty"];
  const showRR = rrViews.includes(view);

  return (
    <div className={"app " + (!showRR ? "no-rightrail" : "")}>
      <WsRail view={view} setView={setView} openVault={() => setVaultOpen(true)}/>
      <TopBar view={view} channel={channel}/>
      <Sidebar
        view={view} setView={setView}
        channel={channel} setChannel={setChannel}
        currentAgent={currentAgent} setCurrentAgent={setCurrentAgent}
      />
      <main className="main" data-screen-label={"View: " + view}>
        {view === "channel" && <ChannelView channel={channel}/>}
        {view === "personal" && <PersonalView currentAgent={currentAgent} setCurrentAgent={setCurrentAgent}/>}
        {view === "search" && <SearchView/>}
        {view === "profile" && <ProfileView agentId={currentAgent}/>}
        {view === "workspace" && <WorkspaceView channel={channel}/>}
        {view === "empty" && <EmptyChannelView channel={channel}/>}
      </main>
      {showRR && <RightRail view={view} channel={channel} currentAgent={currentAgent}/>}
      <Archive openVault={() => setVaultOpen(true)}/>
      {vaultOpen && <Vault onClose={() => setVaultOpen(false)}/>}

      <TweaksPanel title="Tweaks">
        <TweakSection label="Theme"/>
        <TweakToggle label="Dark mode" value={t.dark} onChange={v => setTweak("dark", v)}/>
        <TweakColor
          label="Agent hue"
          value={`oklch(0.74 0.16 ${t.agentHue})`}
          options={[
            "oklch(0.74 0.16 282)",
            "oklch(0.74 0.16 192)",
            "oklch(0.74 0.16 142)",
            "oklch(0.74 0.16 32)",
            "oklch(0.74 0.16 332)",
          ]}
          onChange={v => {
            const m = v.match(/(\d+)\)/);
            if (m) setTweak("agentHue", parseInt(m[1], 10));
          }}
        />
        <TweakSection label="Jump to"/>
        <TweakButton onClick={() => { setView("channel"); setChannel("recist-protocol"); }}>Channel · #recist-protocol</TweakButton>
        <TweakButton onClick={() => setView("personal")}>Personal · chat with Donna</TweakButton>
        <TweakButton onClick={() => setView("search")}>Search & history</TweakButton>
        <TweakButton onClick={() => { setView("profile"); setCurrentAgent("donna"); }}>Agent profile · Donna</TweakButton>
        <TweakButton onClick={() => { setView("workspace"); setChannel("recist:overview"); }}>Project workspace · Recist</TweakButton>
        <TweakButton onClick={() => { setView("empty"); setChannel("recist-models"); }}>Empty channel · onboarding</TweakButton>
        <TweakSection label="Vault"/>
        <TweakToggle label="Open vault" value={vaultOpen} onChange={v => setVaultOpen(v)}/>
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
