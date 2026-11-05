import { useStore } from "../store";
import { AGENTS, AGENT_IDS } from "../types";
import { API_URL, USE_MOCK } from "../lib/api";
import { Field, PageHeader, Segmented, btn, input } from "../components/ui";

export default function SettingsPage() {
  const { theme, setTheme, jurisdiction, setJurisdiction, models, agentModels, setAgentModel, resetAll } = useStore();
  return (
    <>
      <PageHeader title="Settings" />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-8 px-4 py-6">
          <section className="space-y-3">
            <h2 className="font-serif text-xl font-semibold">Appearance</h2>
            <Segmented value={theme} onChange={setTheme} options={[{ id: "system", label: "System" }, { id: "light", label: "Light" }, { id: "dark", label: "Dark" }]} />
          </section>

          <section className="space-y-3">
            <h2 className="font-serif text-xl font-semibold">Default jurisdiction</h2>
            <p className="text-sm text-muted">Used for new chats that are not linked to a case. A case uses its own jurisdiction.</p>
            <div className="max-w-xs"><Field label="Jurisdiction"><input className={input} value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} /></Field></div>
          </section>

          <section className="space-y-3">
            <h2 className="font-serif text-xl font-semibold">Model for each agent</h2>
            <p className="text-sm text-muted">These choices are sent with every request. Choose "Auto routing" to let the backend pick. Use different model families for the argument and counter-argument agents.</p>
            <div className="divide-y divide-line rounded-xl border border-line bg-panel">
              {AGENT_IDS.map((a) => (
                <div key={a} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1 basis-56"><p className="text-sm font-medium">{AGENTS[a].name}</p><p className="text-xs text-muted">{AGENTS[a].role}</p></div>
                  <select aria-label={`Model for ${AGENTS[a].name}`} className={input + " max-w-56"} value={agentModels[a]} onChange={(e) => setAgentModel(a, e.target.value)}>
                    {models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                  </select>
                </div>
              ))}
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="font-serif text-xl font-semibold">Backend</h2>
            <p className="text-sm">{USE_MOCK ? "Demo mode: answers are sample data. Set VITE_API_URL to connect your Modal backend." : <>Connected to <code className="rounded bg-sunk px-1">{API_URL}</code></>}</p>
          </section>

          <section className="space-y-3">
            <h2 className="font-serif text-xl font-semibold">Local data</h2>
            <p className="text-sm text-muted">Cases, chats and deadlines are stored in this browser. Clearing them does not touch the backend.</p>
            <button className={btn + " text-bad"} onClick={() => confirm("Delete all cases, chats and deadlines stored in this browser?") && resetAll()}>Clear local data</button>
          </section>
        </div>
      </div>
    </>
  );
}
