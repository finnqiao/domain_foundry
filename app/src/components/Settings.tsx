import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { PackCard, ProviderTierStatus, ProvidersStatus } from "../lib/types";
import type { SettingsTab } from "../lib/nav";
import { useNav } from "../lib/nav";
import { Docs } from "./Docs";
import { HealthPanel } from "./HealthPanel";
import { Sources } from "./Sources";

const TABS: { id: SettingsTab; label: string }[] = [
  { id: "sources", label: "Sources" },
  { id: "providers", label: "Providers" },
  { id: "health", label: "Health" },
  { id: "docs", label: "Docs" },
];

export function Settings({
  tab,
  packs,
  refreshKey,
}: {
  tab: SettingsTab | undefined;
  packs: PackCard[];
  refreshKey: number;
}) {
  const { navigate } = useNav();
  const activeTab = tab ?? "sources";
  const activeIndex = TABS.findIndex((item) => item.id === activeTab);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function moveTab(offset: number) {
    const next = TABS[(activeIndex + offset + TABS.length) % TABS.length];
    navigate({ name: "settings", tab: next.id });
    window.requestAnimationFrame(() => tabRefs.current[next.id]?.focus());
  }

  return (
    <div className="settings">
      <section className="surface-intro">
        <div>
          <h1>Settings</h1>
          <p className="muted">Sources, provider status, and the parts that make your passions work.</p>
        </div>
        <span className="today-count">{packs.length} {packs.length === 1 ? "passion" : "passions"}</span>
      </section>

      <div
        className="tabs settings-tabs"
        role="tablist"
        tabIndex={-1}
        aria-label="Settings sections"
        onKeyDown={(event) => {
          if (event.key === "ArrowRight" || event.key === "ArrowDown") {
            event.preventDefault();
            moveTab(1);
          } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
            event.preventDefault();
            moveTab(-1);
          }
        }}
      >
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`settings-tab-${item.id}`}
            aria-selected={activeTab === item.id}
            aria-controls="settings-panel"
            tabIndex={activeTab === item.id ? 0 : -1}
            className={`tab${activeTab === item.id ? " tab-active" : ""}`}
            ref={(element) => { tabRefs.current[item.id] = element; }}
            onClick={() => navigate({ name: "settings", tab: item.id })}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div id="settings-panel" className="settings-panel" role="tabpanel" aria-labelledby={`settings-tab-${activeTab}`}>
        {activeTab === "sources" && <Sources />}
        {activeTab === "providers" && <Providers />}
        {activeTab === "health" && <HealthPanel refreshKey={refreshKey} />}
        {activeTab === "docs" && <Docs />}
      </div>
    </div>
  );
}

function Providers() {
  const [status, setStatus] = useState<ProvidersStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.providers().then(setStatus).catch((error) => {
      setErr(error instanceof ApiError ? error.message : String(error));
    });
  }, []);

  if (err) {
    return (
      <section className="panel provider-unavailable" aria-live="polite">
        <h2>Providers</h2>
        <p>Provider status isn’t available in this server build yet.</p>
        <p className="muted">
          Captures still save. Run <code>domain-foundry setup --show</code> in a terminal to inspect provider settings.
        </p>
      </section>
    );
  }
  if (!status) return <p className="muted">Loading provider status…</p>;

  return (
    <section className="panel providers-panel">
      <div className="section-head">
        <div>
          <h2>Providers</h2>
          <p className="muted">
            {status.provider || "Not configured"} · {status.mode || "keyword rules only"}
          </p>
        </div>
        <span className={`badge ${isLive(status) ? "status-applied" : "status-review"}`}>
          {isLive(status) ? "live" : "keyword rules only"}
        </span>
      </div>

      <div className="provider-grid">
        {(["routine", "sota"] as const).map((tier) => (
          <ProviderCard key={tier} tier={tier} value={status[tier]} />
        ))}
      </div>

      {status.detected_env_keys.length > 0 && (
        <div className="provider-env">
          <h3>Keys found in your environment</h3>
          <ul>
            {status.detected_env_keys.map((key) => (
              <li key={`${key.provider}:${key.env}`}><code>{key.env}</code> ({key.provider})</li>
            ))}
          </ul>
        </div>
      )}
      {!isLive(status) && (
        <p className="provider-warning">
          This tier has no working key — captures still save, but routing uses keyword rules. Run <code>domain-foundry setup</code> in a terminal to fix it.
        </p>
      )}
    </section>
  );
}

function ProviderCard({ tier, value }: { tier: "routine" | "sota"; value: ProviderTierStatus }) {
  return (
    <article className="provider-card">
      <div className="provider-card-head">
        <div>
          <h3>{tier === "sota" ? "Deep design" : "Everyday routing"}</h3>
          <span className="muted">{tier === "sota" ? "for shaping a new passion" : "for everyday filing"}</span>
        </div>
        <span className={`dot ${value.live ? "dot-ok" : "dot-bad"}`} aria-label={value.live ? "Live" : "Not live"} />
      </div>
      <dl className="kv">
        <div className="kv-row"><dt>Model</dt><dd>{value.model || "Not selected"}</dd></div>
        <div className="kv-row"><dt>Service</dt><dd>{host(value.base_url)}</dd></div>
        <div className="kv-row"><dt>Key source</dt><dd>{value.api_key_env || "stored in config"}</dd></div>
      </dl>
      {!value.live && (
        <p className="provider-tier-warning">
          This tier has no working key — captures still save, but routing uses keyword rules.
        </p>
      )}
    </article>
  );
}

function isLive(status: ProvidersStatus): boolean {
  return status.routine.live || status.sota.live;
}

function host(value: string | null): string {
  if (!value) return "Default service";
  try {
    return new URL(value).host;
  } catch {
    return value;
  }
}
