import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { describeReceipt } from "../lib/receipts";
import type { AskResponse, CaptureReceipt, PackCard } from "../lib/types";
import { useNav } from "../lib/nav";

type Mode = "log" | "ask";

export function consumeJustInstalled(domain: string): boolean {
  try {
    if (window.sessionStorage.getItem("df:just-installed") !== domain) return false;
    window.sessionStorage.removeItem("df:just-installed");
    return true;
  } catch {
    return false;
  }
}

export function Composer({
  domain,
  packs,
  focusOnMount = false,
  onDone,
}: {
  domain?: string;
  packs: PackCard[];
  focusOnMount?: boolean;
  onDone: (receipt: CaptureReceipt | null) => void;
}) {
  const { openDetail } = useNav();
  const [mode, setMode] = useState<Mode>("log");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState<CaptureReceipt | null>(null);
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const boxRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (focusOnMount) boxRef.current?.focus();
  }, [focusOnMount]);

  const packTitle = packs.find((pack) => pack.name === domain)?.title;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      if (mode === "log") {
        const nextReceipt = await api.capture(text, { domainHint: domain });
        setReceipt(nextReceipt);
        setAnswer(null);
        setText("");
        onDone(nextReceipt);
      } else {
        const nextAnswer = await api.ask(text, { domain });
        setAnswer(nextAnswer);
        setReceipt(null);
        onDone(null);
      }
    } catch (error) {
      const message = error instanceof ApiError ? error.message : String(error);
      setErr(`${message}. Your text was not saved — copy it and try again.`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      <div className="composer-head">
        <div className="seg" role="tablist" aria-label="Composer mode">
          {(["log", "ask"] as Mode[]).map((nextMode) => (
            <button
              key={nextMode}
              type="button"
              role="tab"
              aria-selected={mode === nextMode}
              className={`seg-btn${mode === nextMode ? " seg-active" : ""}`}
              onClick={() => {
                setMode(nextMode);
                setErr(null);
              }}
            >
              {nextMode === "log" ? "Log" : "Ask"}
            </button>
          ))}
        </div>
        {packTitle && <span className="composer-scope muted">in {packTitle}</span>}
      </div>

      <textarea
        ref={boxRef}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === "Enter") void submit(event);
        }}
        placeholder={
          mode === "log"
            ? packTitle
              ? `Log something in ${packTitle}…`
              : "Log anything… e.g. “baked a 75% hydration country loaf”"
            : packTitle
              ? `Ask about ${packTitle}… e.g. “when did I last bake?”`
              : "Ask about anything you've logged…"
        }
        rows={2}
        aria-label={mode === "log" ? "Log text" : "Ask a question"}
      />
      <div className="capture-row">
        <span className="capture-kbd">⌘/Ctrl + Enter</span>
        <button type="submit" className="btn-primary" disabled={busy || !text.trim()}>
          {busy ? (mode === "log" ? "Saving…" : "Thinking…") : mode === "log" ? "Save" : "Ask"}
        </button>
      </div>

      {err && <p className="error" role="alert">{err}</p>}
      {receipt && <ReceiptLine receipt={receipt} packs={packs} />}
      {answer && <AnswerCard answer={answer} onOpenDetail={openDetail} />}
    </form>
  );
}

function ReceiptLine({ receipt, packs }: { receipt: CaptureReceipt; packs: PackCard[] }) {
  const description = describeReceipt(receipt, packs);
  return (
    <div className={`capture-receipt tone-${description.tone}`} role="status">
      <strong>{description.headline}</strong>
      {description.detail && <span className="muted">{description.detail}</span>}
    </div>
  );
}

function AnswerCard({
  answer,
  onOpenDetail,
}: {
  answer: AskResponse;
  onOpenDetail: (target: { domain: string; objectType: string; uid: string }) => void;
}) {
  const cap = answer.daily_cap_usd ?? 0.25;
  const cost = answer.cost_usd ?? 0;
  const hasModel = answer.mode === "llm" && answer.model;

  return (
    <section className="answer-card" aria-live="polite" aria-label="Answer">
      <p className="answer-text">{answer.answer}</p>
      {answer.citations.length > 0 && (
        <div className="citation-list" aria-label="Sources">
          {answer.citations.map((citation, index) => {
            const clickable = Boolean(
              citation.object_uid && citation.domain && citation.object_type,
            );
            const label = citation.snippet || `Source ${index + 1}`;
            return (
              <button
                key={`${citation.entry_id ?? citation.object_uid ?? index}`}
                type="button"
                className="citation-chip"
                disabled={!clickable}
                title={clickable ? "Open the saved record" : "This source is a journal entry"}
                onClick={() => {
                  if (clickable) {
                    onOpenDetail({
                      domain: citation.domain as string,
                      objectType: citation.object_type as string,
                      uid: citation.object_uid as string,
                    });
                  }
                }}
              >
                {label.length > 100 ? `${label.slice(0, 97)}…` : label}
              </button>
            );
          })}
        </div>
      )}
      {answer.mode === "search_only" && (
        <p className="cost-line muted">
          {answer.cap_hit
            ? `Today's model budget (${cap.toFixed(2)}/day) is used up, so this is search-only until tomorrow.`
            : "Search-only mode (no model configured)."}
        </p>
      )}
      {hasModel && (
        <p className="cost-line muted">
          answered with {answer.model}, ~${cost.toFixed(4)}; cap ${cap.toFixed(2)}/day
        </p>
      )}
    </section>
  );
}
