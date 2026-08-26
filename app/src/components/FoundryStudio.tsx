import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../lib/api";
import type {
  FoundryCompletionResponse,
  FoundryGoldenSummary,
  FoundryProposalResponse,
  FoundrySpec,
} from "../lib/types";

type Stage = "brief" | "concepts" | "model" | "app";
type FragmentKind = "workflow" | "schema" | "interaction" | "visual_system" | "concept";

const STAGES: Array<{ id: Stage; label: string; note: string }> = [
  { id: "brief", label: "Research", note: "real practice" },
  { id: "concepts", label: "Three cuts", note: "product hypotheses" },
  { id: "model", label: "Model + experience", note: "one contract" },
  { id: "app", label: "Owned app", note: "preview equals export" },
];

export function FoundryStudio() {
  const [stage, setStage] = useState<Stage>("brief");
  const [goldens, setGoldens] = useState<FoundryGoldenSummary[]>([]);
  const [proposalResult, setProposalResult] = useState<FoundryProposalResponse | null>(null);
  const [completion, setCompletion] = useState<FoundryCompletionResponse | null>(null);
  const [goldenSpec, setGoldenSpec] = useState<FoundrySpec | null>(null);
  const [selectedConcept, setSelectedConcept] = useState("");
  const [goal, setGoal] = useState("");
  const [artifacts, setArtifacts] = useState("");
  const [constraints, setConstraints] = useState("");
  const [taskOne, setTaskOne] = useState("");
  const [expectedOne, setExpectedOne] = useState("");
  const [taskTwo, setTaskTwo] = useState("");
  const [expectedTwo, setExpectedTwo] = useState("");
  const [decision, setDecision] = useState("");
  const [borrowFrom, setBorrowFrom] = useState("");
  const [borrowKind, setBorrowKind] = useState<FragmentKind>("workflow");
  const [borrowFragment, setBorrowFragment] = useState("");
  const [borrowReason, setBorrowReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mobilePreview, setMobilePreview] = useState(false);

  useEffect(() => {
    api.foundryGoldens().then(setGoldens).catch(() => setGoldens([]));
  }, []);

  const activeSpec = completion?.spec ?? goldenSpec;
  const appHtml = completion?.owned_app_html ?? goldenSpec?.owned_app_html;
  const proposal = proposalResult?.proposal;
  const selected = proposal?.concepts.find((item) => item.id === selectedConcept);
  const otherConcepts = proposal?.concepts.filter((item) => item.id !== selectedConcept) ?? [];
  const stageAvailable = useMemo(
    () => ({
      brief: true,
      concepts: Boolean(proposal),
      model: Boolean(activeSpec),
      app: Boolean(appHtml),
    }),
    [proposal, activeSpec, appHtml],
  );

  async function propose(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.foundryPropose({
        goal: goal.trim(),
        artifacts: lines(artifacts),
        constraints: lines(constraints),
        acceptance_tasks: [
          { input: taskOne.trim(), expected: expectedOne.trim() },
          { input: taskTwo.trim(), expected: expectedTwo.trim() },
        ],
        web_research: true,
      });
      setProposalResult(result);
      setSelectedConcept(result.proposal.concepts[0]?.id ?? "");
      setDecision("");
      setCompletion(null);
      setGoldenSpec(null);
      setStage("concepts");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function complete() {
    if (!proposalResult || !selectedConcept || !decision.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const fragments = borrowFrom && borrowFragment.trim() && borrowReason.trim()
        ? [{
            kind: borrowKind,
            from_concept: borrowFrom,
            fragment: borrowFragment.trim(),
            reason: borrowReason.trim(),
            evidence_ids: [],
          }]
        : [];
      const result = await api.foundryComplete(proposalResult.proposal_id, {
        selected_concept: selectedConcept,
        user_decisions: [decision.trim()],
        fragments,
      });
      setCompletion(result);
      setGoldenSpec(null);
      setStage("model");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function inspectGolden(id: string) {
    setBusy(true);
    setError(null);
    try {
      const spec = await api.foundryGolden(id);
      setGoldenSpec(spec);
      setCompletion(null);
      setProposalResult(null);
      setStage("model");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="foundry-studio">
      <header className="foundry-mast">
        <div>
          <p className="foundry-kicker">Evidence to owned application</p>
          <h1>Build around the practice, not the prompt.</h1>
        </div>
        <p className="foundry-lede">
          Research the real activity. Compare three product hypotheses. Remix with lineage.
          Compile the schema, experience, app, evidence, and proof from one specification.
        </p>
      </header>

      <nav className="foundry-rail" aria-label="Foundry stages">
        {STAGES.map((item, index) => (
          <button
            type="button"
            key={item.id}
            disabled={!stageAvailable[item.id]}
            aria-current={stage === item.id ? "step" : undefined}
            onClick={() => setStage(item.id)}
          >
            <span className="foundry-stage-index">{String(index + 1).padStart(2, "0")}</span>
            <span>{item.label}<small>{item.note}</small></span>
          </button>
        ))}
      </nav>

      {error && <div className="foundry-error" role="alert"><strong>Cannot continue</strong><p>{error}</p></div>}

      {stage === "brief" && (
        <BriefStage
          goal={goal}
          setGoal={setGoal}
          artifacts={artifacts}
          setArtifacts={setArtifacts}
          constraints={constraints}
          setConstraints={setConstraints}
          taskOne={taskOne}
          setTaskOne={setTaskOne}
          expectedOne={expectedOne}
          setExpectedOne={setExpectedOne}
          taskTwo={taskTwo}
          setTaskTwo={setTaskTwo}
          expectedTwo={expectedTwo}
          setExpectedTwo={setExpectedTwo}
          busy={busy}
          onSubmit={propose}
          goldens={goldens}
          onGolden={(id) => void inspectGolden(id)}
        />
      )}

      {stage === "concepts" && proposal && (
        <section className="foundry-stage" aria-labelledby="concept-heading">
          <div className="foundry-stage-head">
            <div><p className="foundry-kicker">Three cuts — product concepts</p><h2 id="concept-heading">Choose a loop, then splice deliberately.</h2></div>
            <p>{proposal.research.desired_outcome}</p>
          </div>
          <div className="foundry-concepts">
            {proposal.concepts.map((concept) => (
              <label className={`foundry-concept${concept.id === selectedConcept ? " selected" : ""}`} key={concept.id}>
                <input type="radio" name="concept" value={concept.id} checked={concept.id === selectedConcept} onChange={() => setSelectedConcept(concept.id)} />
                <span className="foundry-kicker">{concept.id}</span>
                <strong>{concept.title}</strong>
                <span>{concept.thesis}</span>
                <dl><dt>Primary loop</dt><dd>{concept.primary_loop}</dd><dt>Affordance</dt><dd>{concept.primary_affordance}</dd></dl>
                <ul>{concept.tradeoffs.map((item) => <li key={item}>{item}</li>)}</ul>
              </label>
            ))}
          </div>
          <div className="foundry-decision-grid">
            <div className="foundry-paper">
              <p className="foundry-kicker">Evidence monitor</p>
              <h3>{proposalResult.candidate_sources} candidates, {proposal.evidence.length} bounded claims</h3>
              {proposal.evidence.slice(0, 6).map((item) => (
                <article className="foundry-evidence" key={item.id}>
                  <span>{item.use} · {item.source_id}</span><p>{item.claim}</p>
                </article>
              ))}
            </div>
            <div className="foundry-paper">
              <p className="foundry-kicker">Remix lineage</p>
              <h3>{selected ? `Base: ${selected.title}` : "Select a base"}</h3>
              <label>Your decision<textarea maxLength={2000} value={decision} onChange={(event) => setDecision(event.target.value)} placeholder="Why this product loop fits how I actually work…" /></label>
              <details>
                <summary>Borrow one fragment from another cut</summary>
                <div className="foundry-form-grid compact">
                  <label>From concept<select value={borrowFrom} onChange={(event) => setBorrowFrom(event.target.value)}><option value="">No borrowed fragment</option>{otherConcepts.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
                  <label>Fragment kind<select value={borrowKind} onChange={(event) => setBorrowKind(event.target.value as FragmentKind)}><option value="workflow">Workflow</option><option value="schema">Schema</option><option value="interaction">Interaction</option><option value="visual_system">Visual system</option><option value="concept">Concept</option></select></label>
                  <label>What to borrow<input maxLength={2000} value={borrowFragment} onChange={(event) => setBorrowFragment(event.target.value)} /></label>
                  <label>Why it belongs<input maxLength={2000} value={borrowReason} onChange={(event) => setBorrowReason(event.target.value)} /></label>
                </div>
              </details>
              <button className="foundry-action" type="button" disabled={busy || !selectedConcept || !decision.trim()} onClick={() => void complete()}>{busy ? "Deriving model and experience…" : "Compile this remix"}</button>
            </div>
          </div>
        </section>
      )}

      {stage === "model" && activeSpec && (
        <ModelStage spec={activeSpec} onOpenApp={() => setStage("app")} hasApp={Boolean(appHtml)} />
      )}

      {stage === "app" && activeSpec && appHtml && (
        <section className="foundry-stage" aria-labelledby="app-heading">
          <div className="foundry-stage-head"><div><p className="foundry-kicker">Preview equals owned export</p><h2 id="app-heading">The compiled application.</h2></div><p>This exact HTML is in the owned bundle beside its schema, evidence snapshot, and build receipt.</p></div>
          <div className="foundry-preview-tools"><button type="button" aria-pressed={!mobilePreview} onClick={() => setMobilePreview(false)}>Desktop</button><button type="button" aria-pressed={mobilePreview} onClick={() => setMobilePreview(true)}>Mobile</button>{completion && <span>{Object.keys(completion.artifacts).length} inspectable artifacts written locally</span>}</div>
          <iframe className={`foundry-app-frame${mobilePreview ? " mobile" : ""}`} title={`${activeSpec.title} application`} sandbox="allow-scripts allow-modals allow-downloads allow-popups" srcDoc={appHtml} />
        </section>
      )}
    </div>
  );
}

function BriefStage(props: {
  goal: string; setGoal: (value: string) => void;
  artifacts: string; setArtifacts: (value: string) => void;
  constraints: string; setConstraints: (value: string) => void;
  taskOne: string; setTaskOne: (value: string) => void;
  expectedOne: string; setExpectedOne: (value: string) => void;
  taskTwo: string; setTaskTwo: (value: string) => void;
  expectedTwo: string; setExpectedTwo: (value: string) => void;
  busy: boolean; onSubmit: (event: FormEvent) => void;
  goldens: FoundryGoldenSummary[]; onGolden: (id: string) => void;
}) {
  return <section className="foundry-stage" aria-labelledby="brief-heading">
    <div className="foundry-stage-head"><div><p className="foundry-kicker">Research brief</p><h2 id="brief-heading">What do you actually do?</h2></div><p>Acceptance tasks are written by you and retained as independent tests. The generator is not allowed to invent its judge.</p></div>
    <form className="foundry-brief" onSubmit={props.onSubmit}>
      <div className="foundry-paper foundry-form-grid">
        <label className="wide">Interest and desired outcome<textarea required maxLength={4000} value={props.goal} onChange={(event) => props.setGoal(event.target.value)} placeholder="I collect vintage trail maps and want to understand where, when, and why each one matters…" /></label>
        <label>Existing artifacts<textarea maxLength={20000} value={props.artifacts} onChange={(event) => props.setArtifacts(event.target.value)} placeholder={'One per line\nSpreadsheet export\nPhoto folder'} /></label>
        <label>Constraints<textarea maxLength={20000} value={props.constraints} onChange={(event) => props.setConstraints(event.target.value)} placeholder={'One per line\nWorks offline\nPhone capture'} /></label>
      </div>
      <div className="foundry-paper">
        <p className="foundry-kicker">Two release tasks — authored by you</p>
        <div className="foundry-task"><span>01</span><label>What will you do?<input required maxLength={2000} value={props.taskOne} onChange={(event) => props.setTaskOne(event.target.value)} /></label><label>What observable result means it worked?<input required maxLength={2000} value={props.expectedOne} onChange={(event) => props.setExpectedOne(event.target.value)} /></label></div>
        <div className="foundry-task"><span>02</span><label>What will you do?<input required maxLength={2000} value={props.taskTwo} onChange={(event) => props.setTaskTwo(event.target.value)} /></label><label>What observable result means it worked?<input required maxLength={2000} value={props.expectedTwo} onChange={(event) => props.setExpectedTwo(event.target.value)} /></label></div>
        <p className="foundry-provider-note">Your configured model receives this brief and the artifact descriptions. When Brave research is configured, it receives generated search queries. Do not paste API keys, passwords, or other secrets.</p>
        <button className="foundry-action" type="submit" disabled={props.busy}>{props.busy ? "Researching sources and product cuts…" : "Research and propose three cuts"}</button>
      </div>
    </form>
    <div className="foundry-golden-head"><div><p className="foundry-kicker">Reviewed verticals</p><h3>Inspect the quality bar first.</h3></div><p>These are structurally different applications, not color variants.</p></div>
    <div className="foundry-goldens">{props.goldens.map((item) => <button type="button" key={item.id} onClick={() => props.onGolden(item.id)}><span className="foundry-kicker">{item.topology} · {item.source_count} sources</span><strong>{item.title}</strong><span>{item.desired_outcome}</span><small>{item.entities} entities · {item.views} views · {item.visual_world.name}</small></button>)}</div>
  </section>;
}

function ModelStage({ spec, onOpenApp, hasApp }: { spec: FoundrySpec; onOpenApp: () => void; hasApp: boolean }) {
  return <section className="foundry-stage" aria-labelledby="model-heading">
    <div className="foundry-stage-head"><div><p className="foundry-kicker">Workloads → model → experience</p><h2 id="model-heading">{spec.title}</h2></div><p>{spec.research.desired_outcome}</p></div>
    <div className="foundry-model-grid">
      <div className="foundry-paper"><p className="foundry-kicker">Identity and lifecycle</p><h3>{spec.domain.entities.length} domain entities</h3><div className="foundry-entities">{spec.domain.entities.map((item) => <article key={item.id}><span>{item.kind}</span><strong>{item.title}</strong><small>identity: {item.identity.join(" + ")}</small><p>{item.description}</p></article>)}</div></div>
      <div className="foundry-paper"><p className="foundry-kicker">Stored invariants</p><h3>{spec.domain.relationships.length} relationships</h3>{spec.domain.relationships.map((item) => <div className="foundry-relation" key={item.id}><strong>{item.from_entity}</strong><span>{item.cardinality}</span><strong>{item.to_entity}</strong></div>)}</div>
      <div className="foundry-paper"><p className="foundry-kicker">Questions justify structure</p><h3>Named workloads</h3>{spec.domain.workloads.map((item) => <article className="foundry-workload" key={item.id}><strong>{item.question}</strong><p>{item.acceptance}</p></article>)}</div>
      <div className="foundry-paper"><p className="foundry-kicker">Domain visual contract</p><h3>{spec.experience.visual_world.name}</h3><p>{spec.experience.visual_world.mood}</p><div className="foundry-token-row">{Object.entries(spec.experience.visual_world.tokens).filter(([, value]) => typeof value === "string" && String(value).startsWith("#")).map(([name, value]) => <span key={name} title={`${name}: ${value}`} style={{ background: String(value) }} />)}</div>{spec.experience.views.map((view) => <article className="foundry-view" key={view.id}><strong>{view.title}</strong><span>{view.purpose}</span></article>)}</div>
      <div className="foundry-paper full"><p className="foundry-kicker">Independent proof contract</p><h3>{spec.evaluation.cases.length} cases</h3><div className="foundry-proof">{spec.evaluation.cases.map((item) => <article key={item.id}><span>{item.kind} · {item.authored_by}</span><strong>{item.input}</strong><p>{item.expected}</p></article>)}</div>{hasApp && <button type="button" className="foundry-action" onClick={onOpenApp}>Open the exact compiled app</button>}</div>
    </div>
  </section>;
}

function lines(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}
