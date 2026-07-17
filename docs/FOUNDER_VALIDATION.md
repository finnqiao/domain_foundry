# Founder-as-user-0 validation (private, not committed)

Plan §11 P8 asks the founder to re-express **≥2 real private domains** as private
packs on a production install and file the friction as issues. That work is
**personal and must never land in this public repo** — no personal packs, data,
notes, denylisted names, real places, or vault/SQLite contents. This file is the
**process checklist** to run privately; it deliberately contains no personal
content.

> Hard rule: personal packs live outside this repo (e.g. `~/.domain_foundry/packs`
> on a production install, or a private repo). Nothing here should ever be
> `git add`ed to `domain_foundry`. `scripts/leakscan.py` is the backstop.

## Setup (private machine)

```bash
pipx install domain-foundry-core
domain-foundry init
```

## For each private domain (do ≥2)

1. **Cold start.** Describe the domain in one sentence to the wizard:
   ```bash
   domain-foundry new-domain "…your real goal…"
   ```
   Answer the interview (or `--reply skip` to accept defaults), then let it
   generate + validate + dry-run.
2. **Test-drive.** Feed 10–20 *real* recent captures. For each, note:
   - Did it route to the right object/operation?
   - Were the fields extracted correctly (units, enums)?
   - Did anything get dropped (should be unfiled/ledger, never lost)?
3. **Correct.** Fix at least 3 real mistakes with one-message corrections. Note
   whether the correction stuck and whether the revision chain reads clearly.
4. **Harden.** Use the hardening loop to add a missing field / rename one. Note
   whether the migration applied cleanly and re-validation passed.
5. **Live in it for a week.** Capture as things actually happen (ideally via the
   hermes-agent adapter). Note friction daily.

## Friction log → issues

Capture friction as it happens; file each as a GitHub issue **on the public
repo with synthetic repro only** (translate any real example into a synthetic
one before filing). Suggested tags:

- `routing` — misroutes / ambiguity the L1 rules or hints should fix.
- `fields` — extraction gaps (units, enums, dates).
- `corrections` — correction intents the parser missed.
- `wizard` — bad questions, wrong archetype, weak generated pack.
- `app` — block/view gaps for the domain.
- `adapter` — capture-first friction through hermes-agent.

## Acceptance for the founder run

- [ ] ≥2 real private domains stood up as packs on a production install.
- [ ] ≥10 real captures each, routing + field accuracy noted.
- [ ] ≥3 corrections per domain exercised.
- [ ] ≥1 hardening migration per domain.
- [ ] Friction filed as issues (synthetic repros only).
- [ ] Confirmed: **nothing personal committed** to this repo (`leakscan.py` green).

> Why this isn't automated here: the harness cannot fabricate the founder's real
> domains without inventing personal data, which would violate the synthetic-only
> constraint. The public CI proves the *mechanism* (packs, routing, corrections,
> wizard, adapter) on synthetic corpora; this checklist proves the *lived*
> experience privately.
