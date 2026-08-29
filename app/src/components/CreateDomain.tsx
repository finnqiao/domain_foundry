import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import type { WizardNeighborhood, WizardNeighborhoodCard, WizardTurn } from "../lib/types";
import { useNav } from "../lib/nav";

/** Short, human labels for the kinds of app a person can make. */
const LOOK_PITCH: Record<string, string> = {
  improvement: "compare changes",
  media_dex: "see photos",
  lab: "try variations",
  catalog: "browse a collection",
  atlas: "see places",
  event_log: "follow what happened",
  practice: "return to your practice",
  graph: "see connections",
  plan: "plan ahead",
};
const RESUME_KEY = "df:create-session";

function lookPitch(heroJob?: string | null): string {
  if (!heroJob) return "look";
  return LOOK_PITCH[heroJob] ?? "look";
}

function humanizeWizardMessage(message: string): string {
  let out = message;
  for (const [id, pitch] of Object.entries(LOOK_PITCH)) {
    out = out.replaceAll(`${id} look`, pitch);
  }
  return out.replace(/\s*\(round \d+\)/gi, "");
}

function displayMessage(turn: WizardTurn): string {
  return turn.user_message || humanizeWizardMessage(turn.message);
}

function fieldLabel(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function CreateDomain({ onDone }: { onDone: () => void }) {
  const { navigate } = useNav();
  const [turns, setTurns] = useState<WizardTurn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [shaping, setShaping] = useState<string | null>(null);
  const goalRef = useRef<HTMLTextAreaElement | null>(null);
  const landed = useRef(false);
  const inflight = useRef(0);
  const current = turns[turns.length - 1] ?? null;

  useEffect(() => {
    if (turns.length === 0) goalRef.current?.focus();
  }, [turns.length]);

  useEffect(() => {
    if (turns.length > 0) return;
    let saved: string | null = null;
    try {
      saved = window.sessionStorage.getItem(RESUME_KEY);
    } catch {
      return;
    }
    if (!saved) return;
    setBusy(true);
    api.createResume(saved).then((turn) => {
      if (!turn.release_mode) {
        window.sessionStorage.removeItem(RESUME_KEY);
        return;
      }
      setTurns([turn]);
      setSessionId(turn.session_id);
    }).catch(() => {
      try {
        window.sessionStorage.removeItem(RESUME_KEY);
      } catch {
        // The session can still be started again from the prompt.
      }
    }).finally(() => setBusy(false));
  }, [turns.length]);

  const openDomain = useCallback((domain: string | null | undefined, shortlist?: string[] | null) => {
    if (!domain || landed.current) return;
    landed.current = true;
    try {
      window.sessionStorage.removeItem(RESUME_KEY);
      window.sessionStorage.setItem("df:just-installed", domain);
      if (shortlist && shortlist.length > 0) {
        window.sessionStorage.setItem("df:shortlist", JSON.stringify(shortlist.slice(0, 8)));
        window.sessionStorage.setItem("df:shortlist-domain", domain);
      }
    } catch {
      // Domain remains usable without the focus hint.
    }
    onDone();
    navigate({ name: "domain", domain });
  }, [navigate, onDone]);

  useEffect(() => {
    if (!current?.domain) return;
    // Keep the person in the creation journey until one real note has been
    // saved. The app is useful before that, but “ready” needs a first-use proof.
    const ready = current.state === "done" && Boolean(current.done);
    if (ready) {
      openDomain(current.domain, current.shortlist ?? null);
    }
  }, [current, openDomain]);

  async function start(event: FormEvent) {
    event.preventDefault();
    if (!input.trim()) return;
    const id = ++inflight.current;
    setBusy(true);
    setErr(null);
    setShaping("Looking at what you want to do…");
    try {
      const turn = await api.createStart(input.trim());
      if (id !== inflight.current) {
        void api.createCancel(turn.session_id).catch(() => undefined);
        return;
      }
      setTurns([turn]);
      setSessionId(turn.session_id);
      try {
        window.sessionStorage.setItem(RESUME_KEY, turn.session_id);
      } catch {
        // Creation remains usable when session storage is unavailable.
      }
      setInput("");
      setShaping(null);
    } catch (error) {
      if (id !== inflight.current) return;
      setErr(error instanceof ApiError ? error.message : String(error));
      setShaping(null);
    } finally {
      if (id === inflight.current) setBusy(false);
    }
  }

  async function reply(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    const id = ++inflight.current;
    if (!sessionId) {
      setBusy(false);
      setShaping(null);
      return;
    }
    setBusy(true);
    setErr(null);
    setShaping(turnProgressLabel(current));
    try {
      const turn = await api.createReply(sessionId, trimmed);
      if (id !== inflight.current) return;
      setTurns((previous) => [...previous, turn]);
      setInput("");
    } catch (error) {
      if (id !== inflight.current) return;
      setErr(error instanceof ApiError ? error.message : String(error));
    } finally {
      if (id === inflight.current) setBusy(false);
    }
  }

  async function cancelCreation() {
    if (!sessionId) return;
    const id = ++inflight.current;
    setBusy(true);
    setErr(null);
    try {
      const turn = await api.createCancel(sessionId);
      if (id !== inflight.current) return;
      setTurns((previous) => [...previous, turn]);
      try {
        window.sessionStorage.removeItem(RESUME_KEY);
      } catch {
        // Nothing else depends on the local resume hint.
      }
    } catch (error) {
      if (id !== inflight.current) return;
      setErr(error instanceof ApiError ? error.message : String(error));
    } finally {
      if (id === inflight.current) {
        setShaping(null);
        setBusy(false);
      }
    }
  }

  return (
    <div className="wizard">
      <section className="surface-intro">
        <div>
          <h1>Start something quickly</h1>
          <p className="muted">A quick way to get a place to log things. Name a topic and answer a few questions. For the full build, with research and three concepts to choose from, use the foundry.</p>
        </div>
        <span className="today-count">Quick start</span>
      </section>

      {turns.length === 0 && (
        <section className="wizard-start panel">
          <h2>What would you like an app for?</h2>
          <p className="muted">
            Try “whisky”, “my aquarium”, or “sourdough bakes”. You can describe a
            specific routine too.
          </p>
          <form onSubmit={start}>
            <label className="sr-only" htmlFor="domain-goal">
              What would you like an app for?
            </label>
            <textarea
              id="domain-goal"
              className="wizard-input"
              rows={3}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="whisky, my aquarium, or sourdough bakes"
              ref={goalRef}
            />
            <div className="wizard-actions">
              <button className="btn-primary" type="submit" disabled={busy || !input.trim()}>
                {busy ? "Starting…" : "Continue"}
              </button>
            </div>
          </form>
        </section>
      )}

      {turns.length > 0 && (
        <>
          {current?.progress && <ProgressRail progress={current.progress} />}
          <section className="wizard-turns" aria-label="Creation progress">
            {turns.map((turn, index) => (
              <article
                className={`wizard-turn${index === turns.length - 1 ? " wizard-turn-current" : ""}`}
                key={`${turn.session_id}-${index}`}
              >
                <span className="wizard-speaker">Your guide</span>
                <p>{displayMessage(turn)}</p>
                {turn.shortlist && turn.shortlist.length > 0 && (
                  <div className="wizard-questions" aria-label="What the app may keep track of">
                    {turn.shortlist.map((chip) => (
                      <span className="chip" key={chip}>
                        {fieldLabel(chip)}
                      </span>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </section>
          {current && !landed.current && (
            <WizardStep
              turn={current}
              input={input}
              setInput={setInput}
              busy={busy}
              onReply={reply}
              onOpen={(domain) => openDomain(domain, current.shortlist)}
            />
          )}
        </>
      )}
      {busy && (
        <p className="muted" role="status">
          {shaping ?? "One moment…"}
          {sessionId && (
            <>
              {" "}
              <button className="btn-secondary" type="button" onClick={() => void cancelCreation()}>
                Cancel
              </button>
            </>
          )}
        </p>
      )}
      {err && (
        <p className="error" role="alert">
          {err}
        </p>
      )}
    </div>
  );
}

function turnProgressLabel(turn: WizardTurn | null): string {
  if (!turn) return "Working…";
  switch (turn.phase || turn.state) {
    case "focus":
      return "Finding the right direction…";
    case "notes":
      return "Using your notes…";
    case "ideas":
      return "Preparing a few starting points…";
    case "build":
      return "Putting your app together…";
    case "check":
      return "Trying the second note…";
    case "try":
      return "Saving your first note…";
    default:
      return "Working…";
  }
}

function WizardStep({
  turn,
  input,
  setInput,
  busy,
  onReply,
  onOpen,
}: {
  turn: WizardTurn;
  input: string;
  setInput: (value: string) => void;
  busy: boolean;
  onReply: (text: string) => void;
  onOpen: (domain: string | null | undefined) => void;
}) {
  if (turn.state === "fork" || turn.awaiting === "fork") {
    return (
      <NeighborhoodStep
        turn={turn}
        input={input}
        setInput={setInput}
        busy={busy}
        onReply={onReply}
      />
    );
  }

  if (turn.state === "looks" || turn.awaiting === "look") {
    return (
      <LooksStep
        turn={turn}
        input={input}
        setInput={setInput}
        busy={busy}
        onReply={onReply}
      />
    );
  }

  if (turn.state === "elicit" || turn.awaiting === "elicit") {
    const step = turn.elicit;
    return (
      <section className="wizard-card panel">
        <span className="badge">
          {step ? `Your notes ${step.index}/${step.of}` : "Your notes"}
        </span>
        <h2>{step?.held_out ? "Add a second note" : "Add a note you might write"}</h2>
        <p className="muted">{displayMessage(turn)}</p>
        <WizardReplyForm
          input={input}
          setInput={setInput}
          busy={busy}
          onReply={onReply}
          placeholder="Write it as you would on a normal day…"
          buttonLabel="Use this note"
        />
        <div className="wizard-actions">
          <button className="btn-secondary" type="button" disabled={busy} onClick={() => onReply("skip for now")}>
            Skip for now
          </button>
        </div>
      </section>
    );
  }

  if (turn.state === "model_confirm" || turn.awaiting === "model_confirm") {
    const estimate = turn.designer?.est_cost_usd;
    return (
      <section className="wizard-card panel">
        <span className="badge">A choice for you</span>
        <h2>Use reviewed sources to find more directions?</h2>
        <p className="muted">
          {estimate !== undefined
            ? `This may cost about $${estimate.toFixed(2)} with your current setup. `
            : "This optional step uses your current research setup. "}
          Your notes and choices stay on this computer.
        </p>
        <div className="wizard-actions">
          <button className="btn-primary" type="button" disabled={busy} onClick={() => onReply("continue")}>
            Continue
          </button>
          <button className="btn-secondary" type="button" disabled={busy} onClick={() => onReply("not now")}>
            Not now
          </button>
        </div>
        <details className="wizard-details">
          <summary>See technical details</summary>
          <p className="muted">
            The research step uses the selected design model. You can choose a different setup in Settings.
          </p>
        </details>
      </section>
    );
  }

  if (turn.state === "schema_preview" || turn.awaiting === "schema_confirm") {
    return (
      <section className="wizard-card panel">
        <span className="badge">Your app</span>
        <h2>Here is what your app will keep track of</h2>
        <p className="muted">{displayMessage(turn)}</p>
        <SchemaSummary preview={turn.schema_preview} />
        {turn.schema_preview && (
          <details className="wizard-details">
            <summary>See technical details</summary>
            <pre className="code">{JSON.stringify(turn.schema_preview, null, 2)}</pre>
          </details>
        )}
        <div className="wizard-actions">
          <button className="btn-primary" type="button" disabled={busy} onClick={() => onReply("build this")}>
            Build this app
          </button>
          <button className="btn-secondary" type="button" disabled={busy} onClick={() => onReply("back")}>
            Change direction
          </button>
        </div>
      </section>
    );
  }

  if (turn.awaiting === "confirm" || turn.state === "hardening_confirm") {
    return (
      <section className="wizard-card panel">
        <span className="badge">Review</span>
        <h2>Review the change</h2>
        <p className="muted">{displayMessage(turn)}</p>
        {turn.diff && (
          <details className="wizard-details" open>
            <summary>See the change</summary>
            <pre className="code">{JSON.stringify(turn.diff, null, 2)}</pre>
          </details>
        )}
        <div className="wizard-actions">
          <button className="btn-primary" type="button" disabled={busy} onClick={() => onReply("confirm")}>
            Apply edit
          </button>
          <button className="btn-secondary" type="button" disabled={busy} onClick={() => onReply("cancel")}>
            Cancel
          </button>
        </div>
      </section>
    );
  }

  if (turn.awaiting === "repair") {
    return (
      <section className="wizard-card panel">
        <span className="badge status-review">Needs a little more</span>
        <h2>Let’s adjust this</h2>
        <p className="muted">{displayMessage(turn)}</p>
        <FailureList failures={turn.acceptance?.failures ?? turn.failures ?? []} />
        <WizardReplyForm
          input={input}
          setInput={setInput}
          busy={busy}
          onReply={onReply}
          placeholder="Tell us how this note should be understood…"
          buttonLabel="Adjust it"
        />
        {turn.domain && (
          <button className="btn-primary" type="button" onClick={() => onOpen(turn.domain)}>
            Continue with this version
          </button>
        )}
      </section>
    );
  }

  if (turn.domain && (turn.awaiting === "capture" || turn.state === "test_drive")) {
    const title = turn.pack?.title || turn.domain;
    const hasCapture = Boolean(turn.capture);
    const first = turn.capture?.routed?.[0];
    const captureApplied =
      turn.capture?.status === "applied" &&
      Boolean(first && first.disposition !== "unfiled" && first.disposition !== "ledger_only");
    const captureNeedsHelp = hasCapture && !captureApplied;
    const firstUseBlocked = Boolean(turn.first_use_blocked);
    return (
      <section className="wizard-card panel">
        <span className="badge">
          {captureNeedsHelp ? "Your note is safe" : firstUseBlocked ? "One note first" : hasCapture ? "First use" : "Try it"}
        </span>
        <h2>
          {captureNeedsHelp
            ? "Let’s try that another way"
            : firstUseBlocked
            ? "Add your first note"
            : hasCapture
            ? "Your first note is saved"
            : "Try your first note"}
        </h2>
        <p className="muted">
          {captureNeedsHelp || firstUseBlocked || hasCapture
            ? displayMessage(turn)
            : `Write one real note about ${title}. We’ll keep it here so you can see how it fits.`}
        </p>
        {captureNeedsHelp ? (
          <WizardReplyForm
            input={input}
            setInput={setInput}
            busy={busy}
            onReply={onReply}
            placeholder="Try another real note…"
            buttonLabel="Try another note"
          />
        ) : hasCapture ? (
          <CaptureSummary turn={turn} />
        ) : (
          <WizardReplyForm
            input={input}
            setInput={setInput}
            busy={busy}
            onReply={onReply}
            placeholder="Write one real note, or type “later”…"
            buttonLabel="Save note"
          />
        )}
        {hasCapture && captureApplied && (
          <div className="wizard-actions">
            <button className="btn-primary" type="button" onClick={() => onOpen(turn.domain)}>
              Open your app
            </button>
            <button className="btn-secondary" type="button" disabled={busy} onClick={() => onReply("done")}>
              Done for now
            </button>
          </div>
        )}
      </section>
    );
  }

  if (turn.state === "failed") {
    return (
      <section className="wizard-card panel">
        <span className="badge status-review">Saved</span>
        <h2>Creation stopped</h2>
        <p className="muted">{displayMessage(turn)}</p>
      </section>
    );
  }

  return (
    <section className="wizard-card panel">
      <p className="muted">{displayMessage(turn)}</p>
      <WizardReplyForm input={input} setInput={setInput} busy={busy} onReply={onReply} placeholder="Reply…" />
    </section>
  );
}

function WizardReplyForm({
  input,
  setInput,
  busy,
  onReply,
  placeholder,
  buttonLabel = "Send",
}: {
  input: string;
  setInput: (value: string) => void;
  busy: boolean;
  onReply: (text: string) => void;
  placeholder: string;
  buttonLabel?: string;
}) {
  return (
    <form
      className="wizard-reply"
      onSubmit={(event) => {
        event.preventDefault();
        if (input.trim()) onReply(input);
      }}
    >
      <input
        value={input}
        onChange={(event) => setInput(event.target.value)}
        placeholder={placeholder}
        aria-label="Reply to the domain wizard"
      />
      <button className="btn-primary" type="submit" disabled={busy || !input.trim()}>
        {buttonLabel}
      </button>
    </form>
  );
}

function ProgressRail({
  progress,
}: {
  progress: Array<{ id: string; label: string; status: string }>;
}) {
  return (
    <ol className="wizard-progress" aria-label="Creation progress">
      {progress.map((item) => (
        <li
          className={`wizard-progress-item wizard-progress-${item.status}`}
          key={item.id}
          aria-current={item.status === "active" ? "step" : undefined}
        >
          <span aria-hidden="true">{item.status === "done" ? "✓" : item.status === "active" ? "→" : "·"}</span>
          <span>{item.label}</span>
        </li>
      ))}
    </ol>
  );
}

function SchemaSummary({ preview }: { preview?: Record<string, unknown> | null }) {
  const fields = Array.isArray(preview?.fields) ? preview.fields : [];
  const groups = new Map<string, string[]>();
  for (const value of fields) {
    if (!value || typeof value !== "object") continue;
    const field = value as { object?: unknown; name?: unknown };
    const objectName = String(field.object || "details");
    const names = groups.get(objectName) || [];
    if (field.name) names.push(fieldLabel(String(field.name)));
    groups.set(objectName, names);
  }
  if (groups.size === 0) return <p className="muted">Your notes will shape the details this app keeps.</p>;
  return (
    <div className="wizard-schema-summary">
      {[...groups.entries()].map(([objectName, names]) => (
        <div className="wizard-schema-group" key={objectName}>
          <strong>{fieldLabel(objectName)}</strong>
          <span>{[...new Set(names)].join(", ")}</span>
        </div>
      ))}
    </div>
  );
}

function CaptureSummary({ turn }: { turn: WizardTurn }) {
  const capture = turn.capture;
  const first = capture?.routed?.[0];
  if (!capture || !first || first.disposition === "unfiled" || first.disposition === "ledger_only") {
    return (
      <p className="wizard-capture-note">
        Your note is safe, but it did not go to the right place yet. Try another note below, or come back later.
      </p>
    );
  }
  return (
    <div className="wizard-capture-note">
      <strong>Went to the right place</strong>
      <span>{fieldLabel(String(first.object_type || "note"))}</span>
    </div>
  );
}

function NeighborhoodStep({
  turn,
  input,
  setInput,
  busy,
  onReply,
}: {
  turn: WizardTurn;
  input: string;
  setInput: (value: string) => void;
  busy: boolean;
  onReply: (text: string) => void;
}) {
  const nb: WizardNeighborhood = turn.neighborhood ?? {};
  return (
    <section className="wizard-card panel atlas-browse">
      <span className="badge">Your focus</span>
      <h2>What would you like to do with this?</h2>
      <p className="muted">{displayMessage(turn)}</p>
      {(nb.refine ?? []).length > 0 && (
        <div className="atlas-row">
          <h3>Choose a direction</h3>
          <div className="wizard-questions">
            {(nb.refine ?? []).map((card) => (
              <button
                key={card.id}
                type="button"
                className="chip chip-action"
                disabled={busy}
                onClick={() => onReply(card.title)}
              >
                {card.title}
              </button>
            ))}
          </div>
        </div>
      )}
      {(nb.expand ?? []).length > 0 && (
        <div className="atlas-row">
          <h3>You might also want</h3>
          <div className="wizard-questions">
            {(nb.expand ?? []).map((card) => (
              <button
                key={card.id}
                type="button"
                className="chip chip-action"
                disabled={busy}
                onClick={() => onReply(card.title)}
              >
                {card.title}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="atlas-ideas">
        <h3>Closest matches</h3>
        <div className="atlas-idea-grid">
          {(nb.ideas ?? []).map((idea) => (
            <IdeaCard key={idea.id} idea={idea} busy={busy} onPick={() => onReply(idea.id)} />
          ))}
        </div>
      </div>
      <div className="wizard-actions">
        <button className="btn-secondary" type="button" disabled={busy} onClick={() => onReply("just a simple log")}>
          Start with notes
        </button>
        <button className="btn-secondary" type="button" disabled={busy} onClick={() => onReply("something else")}>
          Describe it in your own words
        </button>
      </div>
      <WizardReplyForm
        input={input}
        setInput={setInput}
        busy={busy}
        onReply={onReply}
        placeholder="Tell us what a normal note might say…"
      />
    </section>
  );
}

function LooksStep({
  turn,
  input,
  setInput,
  busy,
  onReply,
}: {
  turn: WizardTurn;
  input: string;
  setInput: (value: string) => void;
  busy: boolean;
  onReply: (text: string) => void;
}) {
  const looks = turn.looks ?? [];
  return (
    <section className="wizard-card panel atlas-browse">
      <span className="badge">Preview</span>
      <h2>How should it feel to use?</h2>
      <p className="muted">{displayMessage(turn)}</p>
      <div className="look-grid">
        {looks.map((look, index) => {
          const selected = look.idea_id === turn.selected_look_id;
          return (
            <article
              className={`look-card${selected ? " look-card-selected" : ""}`}
              key={look.idea_id}
            >
              <header>
                <strong>
                  {index + 1}. {look.title}
                </strong>
                <span className="muted">{lookPitch(look.hero_job)}</span>
              </header>
              <iframe
                className="look-frame"
                title={look.title}
                sandbox=""
                srcDoc={look.html}
              />
              <button
                className="btn-secondary"
                type="button"
                disabled={busy}
                onClick={() => onReply(String(index + 1))}
              >
                Choose this
              </button>
            </article>
          );
        })}
      </div>
      <div className="wizard-actions">
        <button className="btn-primary" type="button" disabled={busy} onClick={() => onReply("build it")}>
          Use this direction
        </button>
        <button className="btn-secondary" type="button" disabled={busy} onClick={() => onReply("back")}>
          Back
        </button>
      </div>
      <WizardReplyForm
        input={input}
        setInput={setInput}
        busy={busy}
        onReply={onReply}
        placeholder="What should change? e.g. darker or denser…"
      />
    </section>
  );
}

function IdeaCard({
  idea,
  busy,
  onPick,
}: {
  idea: WizardNeighborhoodCard;
  busy: boolean;
  onPick: () => void;
}) {
  const analog = idea.world_analogs?.[0];
  const like = analog?.name?.trim();
  const badgeKind = like ? "world" : "fresh";
  const badgeLabel = like ? `Similar to ${like}` : "Built for your notes";
  return (
    <button type="button" className="atlas-idea" disabled={busy} onClick={onPick}>
      <span className={`atlas-badge atlas-badge-${badgeKind}`}>{badgeLabel}</span>
      {idea.highlighted && <span className="atlas-suggested">Closest to what you described</span>}
      <strong>{idea.title}</strong>
      <p>{idea.pitch}</p>
    </button>
  );
}

function FailureList({ failures }: { failures: Array<Record<string, unknown>> }) {
  if (failures.length === 0) return <p className="muted">The second note needs a little more context.</p>;
  return (
    <ul className="failure-list">
      {failures.map((failure, index) => (
        <li key={index}>
          “{String(failure.text ?? failure.phrase ?? failure.capture ?? "Your note")}”
          {failure.actual ? `: ${String(failure.actual)}` : ": needs a clearer place"}
        </li>
      ))}
    </ul>
  );
}
