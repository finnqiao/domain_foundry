// Plain-language receipts shared by the composer, Today, and Inbox. Internal
// status names stay at this boundary instead of leaking into the product UI.

import type { CaptureReceipt, EntryRow, PackCard } from "./types";

export type ReceiptDescription = {
  tone: "ok" | "unsure" | "error";
  headline: string;
  detail?: string;
  repair: { kind: "refile"; entryId: string } | { kind: "review" } | null;
};

function packTitle(packs: PackCard[], domain: string | null | undefined): string {
  if (!domain || domain === "_unfiled" || domain === "_ledger") return "";
  return packs.find((pack) => pack.name === domain)?.title ?? domain;
}

function humanType(objectType: string | null | undefined): string {
  return (objectType ?? "entry").replace(/_/g, " ");
}

function article(word: string): string {
  return /^[aeiou]/i.test(word) ? "an" : "a";
}

export function describeReceipt(receipt: CaptureReceipt, packs: PackCard[]): ReceiptDescription {
  const real = receipt.routed.filter(
    (span) => span.domain && span.domain !== "_unfiled" && span.domain !== "_ledger",
  );
  const degraded = receipt.llm_error
    ? "Model routing was unavailable, so keyword rules did the filing — check Settings → Providers."
    : undefined;

  switch (receipt.status) {
    case "applied": {
      if (real.length === 1) {
        const span = real[0];
        const type = humanType(span.object_type);
        return {
          tone: "ok",
          headline: `Saved to ${packTitle(packs, span.domain)} as ${article(type)} ${type}`,
          detail: degraded,
          repair: null,
        };
      }
      const names = [...new Set(real.map((span) => packTitle(packs, span.domain)))].filter(Boolean);
      return {
        tone: "ok",
        headline: names.length ? `Saved to ${names.join(" and ")}` : "Saved to your journal",
        detail: degraded,
        repair: null,
      };
    }
    case "review":
      return {
        tone: "unsure",
        headline: "Saved — waiting for your OK before it changes anything",
        detail: degraded ?? "You'll find it in Inbox.",
        repair: { kind: "review" },
      };
    case "unfiled":
      return {
        tone: "unsure",
        headline: "Saved — I wasn't sure where this belongs",
        detail: degraded ?? "File it from Inbox in one click.",
        repair: { kind: "refile", entryId: receipt.entry_id },
      };
    case "ledger_only":
    default:
      return {
        tone: "unsure",
        headline: "Saved to your journal",
        detail: degraded ?? "Install or create a passion and entries like this get filed automatically.",
        repair: null,
      };
  }
}

export function describeRow(row: EntryRow, packs: PackCard[]): ReceiptDescription {
  const fake: CaptureReceipt = {
    entry_id: row.id,
    capture_event_id: row.capture_event_id,
    status: row.status,
    routed: [
      {
        domain: row.domain,
        object_type: row.object_type,
        operation: row.operation,
        disposition: row.status,
        confidence: row.routing_confidence,
      },
    ],
    projection_status: "n/a",
    idempotent_replay: false,
    summary: row.summary,
    llm_error: null,
    domain_hint: null,
  };
  return describeReceipt(fake, packs);
}
