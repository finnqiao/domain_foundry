import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import type { PackCard, WizardNeighborhood, WizardNeighborhoodCard, WizardTurn } from "../lib/types";
import { useNav } from "../lib/nav";

export function CreateDomain({ packs, onDone }: { packs: PackCard[]; onDone: () => void }) {
  const { navigate } = useNav();
  const [turns, setTurns] = useState<WizardTurn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [shaping, setShaping] = useState<string | null>(null);
  const goalRef = useRef<HTMLTextAreaElement | null>(null);
  const landed = useRef(false);
  const current = turns[turns.length - 1] ?? null;

  useEffect(() => {
    if (turns.length === 0) goalRef.current?.focus();
  }, [turns.length]);

  function openDomain(domain: string | null | undefined, shortlist?: string[] | null) {
    if (!domain || landed.current) return;
    landed.current = true;
    try {
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
  }

  useEffect(() => {
    if (!current?.domain) return;
    const ready =
      current.awaiting === "capture" ||
      current.state === "test_drive" ||
      Boolean(current.done);
    if (ready) {
      openDomain(current.domain, current.shortlist ?? null);
    }
  }, [current]);

  async function start(event: FormEvent) {
    event.preventDefault();
    if (!input.trim()) return;
    setBusy(true);
    setErr(null);
    setShaping("Shaping your interest area…");
    try {
      const turn = await api.wizardStart(input.trim());
      setTurns([turn]);
      setSessionId(turn.session_id);
      setInput("");
      if (turn.designer?.model) {
        setShaping(
          `Shaping with ${turn.designer.model}` +
            (typeof turn.designer.est_cost_usd === "number"
              ? ` · ~$${turn.designer.est_cost_usd.toFixed(2)}`
              : ""),
        );
      } else {
        setShaping(null);
      }
    } catch (error) {
      setErr(error instanceof ApiError ? error.message : String(error));
      setShaping(null);
    } finally {
      setBusy(false);
    }
  }

  async function reply(text: string) {
    if (!sessionId || !text.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const turn = await api.wizardReply(sessionId, text.trim());
      setTurns((previous) => [...previous, turn]);
      setInput("");
    } catch (error) {
      setErr(error instanceof ApiError ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="wizard">
      <section className="surface-intro">
        <div>
          <h1>Create your own</h1>
          <p className="muted">Name an interest. We’ll show nearby topics and app ideas — including things that already exist.</p>
        </div>
        <span className="today-count">One sentence</span>
      </section>

      {turns.length === 0 && (
        <section className="wizard-start panel">
          <h2>What do you actually do?</h2>
          <p className="muted">
            Try “food”, “diving”, or “soccer”. You’ll get a map of the territory — then pick an idea
            (or mix) before anything is installed.
          </p>
          <form onSubmit={start}>
            <label className="sr-only" htmlFor="domain-goal">
              Describe your interest area
            </label>
            <textarea
              id="domain-goal"
              className="wizard-input"
              rows={3}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Track my…"
              ref={goalRef}
            />
            <div className="wizard-actions">
              <button className="btn-primary" type="submit" disabled={busy || !input.trim()}>
                {busy ? "Starting…" : "Start"}
              </button>
            </div>
          </form>
        </section>
      )}

      {turns.length > 0 && (
        <>
          <section className="wizard-turns" aria-label="Creation progress">
            {turns.map((turn, index) => (
              <article
                className={`wizard-turn${index === turns.length - 1 ? " wizard-turn-current" : ""}`}
                key={`${turn.session_id}-${index}`}
              >
                <span className="wizard-speaker">Domain Foundry</span>
                <p>{turn.message}</p>
                {turn.shortlist && turn.shortlist.length > 0 && (
                  <div className="wizard-questions" aria-label="Fields we’ll track">
                    {turn.shortlist.map((chip) => (
                      <span className="chip" key={chip}>
                        {chip}
                      </span>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </section>
          {busy && shaping && (
            <p className="muted" role="status">
              {shaping}
              {sessionId && (
                <>
                  {" "}
                  <button className="btn-secondary" type="button" disabled={busy} onClick={() => reply("cancel")}>
                    Cancel
                  </button>
                </>
              )}
            </p>
          )}
          {current && !landed.current && (
            <WizardStep
              turn={current}
              packs={packs}
              input={input}
              setInput={setInput}
              busy={busy}
              onReply={reply}
              onOpen={(domain) => openDomain(domain, current.shortlist)}
            />
          )}
        </>
      )}
      {err && (
        <p className="error" role="alert">
          {err}
        </p>
      )}
    </div>
  );
}

function WizardStep({
  turn,
  packs,
  input,
  setInput,
  busy,
  onReply,
  onOpen,
}: {
  turn: WizardTurn;
  packs: PackCard[];
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

  if (turn.state === "schema_preview" || turn.awaiting === "schema_confirm") {
    return (
      <section className="wizard-card panel">
        <span className="badge">Schema</span>
        <h2>Show schema before activate</h2>
        <p className="muted">{turn.message}</p>
        {turn.schema_preview && (
          <pre className="code">{JSON.stringify(turn.schema_preview, null, 2)}</pre>
        )}
        <div className="wizard-actions">
          <button className="btn-primary" type="button" disabled={busy} onClick={() => onReply("yes")}>
            Build this
          </button>
          <button className="btn-secondary" type="button" disabled={busy} onClick={() => onReply("back")}>
            Back
          </button>
        </div>
      </section>
    );
  }

  // Seamless path: ready turns auto-navigate. Keep hardening/confirm only.
  if (turn.awaiting === "confirm" || turn.state === "hardening_confirm") {
    return (
      <section className="wizard-card panel">
        <span className="badge">Proposed edit</span>
        <h2>Review the change</h2>
        {turn.diff && <pre className="code">{JSON.stringify(turn.diff, null, 2)}</pre>}
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
        <span className="badge status-review">Optional repair</span>
        <h2>Teach this interest area one more thing</h2>
        <FailureList failures={turn.acceptance?.failures ?? turn.failures ?? []} />
        <WizardReplyForm
          input={input}
          setInput={setInput}
          busy={busy}
          onReply={onReply}
          placeholder="Teach a phrase…"
        />
        {turn.domain && (
          <button className="btn-primary" type="button" onClick={() => onOpen(turn.domain)}>
            Open anyway
          </button>
        )}
      </section>
    );
  }

  if (turn.domain && (turn.awaiting === "capture" || turn.state === "test_drive")) {
    const installed = Boolean(packs.some((pack) => pack.name === turn.domain));
    return (
      <section className="wizard-card panel">
        <span className="badge">ready</span>
        <h2>{turn.domain} is ready</h2>
        <p className="muted">Opening your interest area…</p>
        <button className="btn-primary" type="button" onClick={() => onOpen(turn.domain)}>
          {installed ? `Open ${turn.domain}` : `Open ${turn.domain ?? "it"}`}
        </button>
      </section>
    );
  }

  return (
    <section className="wizard-card panel">
      <p className="muted">Continue if needed — or start again from Your passions.</p>
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
}: {
  input: string;
  setInput: (value: string) => void;
  busy: boolean;
  onReply: (text: string) => void;
  placeholder: string;
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
        Send
      </button>
    </form>
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
  const crumb = (nb.breadcrumb ?? []).map((b) => b.title).join(" → ") || "Ideas";
  return (
    <section className="wizard-card panel atlas-browse">
      <span className="badge">You are here</span>
      <h2>{crumb}</h2>
      <p className="muted">{turn.message}</p>
      {(nb.refine ?? []).length > 0 && (
        <div className="atlas-row">
          <h3>Refine</h3>
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
          <h3>People also go here</h3>
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
        <h3>Ideas here</h3>
        <div className="atlas-idea-grid">
          {(nb.ideas ?? []).map((idea) => (
            <IdeaCard key={idea.id} idea={idea} busy={busy} onPick={() => onReply(idea.title)} />
          ))}
        </div>
      </div>
      <div className="wizard-actions">
        <button className="btn-secondary" type="button" disabled={busy} onClick={() => onReply("just a simple log")}>
          Just a simple log
        </button>
        <button className="btn-secondary" type="button" disabled={busy} onClick={() => onReply("show schema")}>
          Show schema
        </button>
        <button className="btn-secondary" type="button" disabled={busy} onClick={() => onReply("something else")}>
          Something else
        </button>
      </div>
      <WizardReplyForm
        input={input}
        setInput={setInput}
        busy={busy}
        onReply={onReply}
        placeholder="Pick an idea, mix two, or describe it…"
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
  const badge =
    idea.provenance === "foundry" ? "fresh" : analog ? "world" : idea.provenance ?? "idea";
  return (
    <button type="button" className="atlas-idea" disabled={busy} onClick={onPick}>
      <span className={`atlas-badge atlas-badge-${badge}`}>{badge}</span>
      {idea.highlighted && <span className="atlas-suggested">suggested</span>}
      <strong>{idea.title}</strong>
      <p>{idea.pitch}</p>
      {analog && <p className="muted">This is like {analog.name}</p>}
    </button>
  );
}

function FailureList({ failures }: { failures: Array<Record<string, unknown>> }) {
  if (failures.length === 0) return <p className="muted">No failures in the current check.</p>;
  return (
    <ul className="failure-list">
      {failures.map((failure, index) => (
        <li key={index}>
          “{String(failure.text ?? failure.phrase ?? failure.capture ?? "Example phrase")}”
          {failure.actual ? ` → ${String(failure.actual)}` : ""}
        </li>
      ))}
    </ul>
  );
}
