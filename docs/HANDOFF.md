# Launch handoff — what I did vs what you do

Provisional name is **Domain Foundry**. Repo is the local `domain_foundry`
checkout (renamed from `domain_expert`).

---

## Done in-repo (agent)

- Mechanical rename complete: PyPI `domain-foundry-core` /
  `domain-foundry-hermes-agent`, CLI `domain-foundry`, packages
  `domain_foundry_core` / `domain_foundry_hermes_agent`, workspace
  `~/.domain_foundry/`, env `DOMAIN_FOUNDRY_*`, hermes entry-point
  `domain_foundry`, docs/mkdocs/README/ADR-005/launch drafts, SPA brand.
- ADR-005 accepted (provisional); LAUNCH_CHECKLIST §0 updated.
- SPA rebuilt (`app/dist`).
- `scripts/release_audit.sh` **green** after rename.
- `scripts/quickstart_gate.sh` **PASS**.
- Synthetic E2E + screenshots in [`docs/assets/evidence/`](assets/evidence/)
  (home → feed with routing badges → domain view → UI capture → correction
  dialog → health).

**Not committed** — say if you want a commit.

---

## Your checklist (explicit steps)

### 1. Name availability (still blocks publish)

```bash
# Recheck all five official PyPI JSON endpoints from release/name-availability.yaml.
# A 404 means no public project exists now; it does not reserve the name.
python scripts/name_availability_audit.py

# Verify the current repository coordinate and your authority over it.
git remote -v
# `Domain-Foundry` is an existing GitHub organization with unverified ownership;
# do not plan to create or claim it without a verified transfer.

# Trademark sanity: USPTO / EUIPO search “Domain Foundry”
```

Do not treat this as an open-ended sanity check: USPTO TSDR currently records
live application `99880503` for **DOMAIN FOUNDRY** by Semantic Foundry LLC with
directly overlapping software services. The current name is release-blocked
until a rename, documented rights agreement, or qualified clearance is recorded.

The currently verified repository is `github.com/finnqiao/domain_foundry`. If
the maintainer chooses another coordinate, update every project URL and rerun
the exact candidate and public-release gates before tagging.

### 2. Commit + push remote (when ready)

```bash
cd /path/to/domain_foundry
# recreate clean venv if needed (old path shebangs break after dir rename):
#   mv .venv /tmp/df_venv_old && python3 -m venv .venv
#   .venv/bin/python -m pip install -e ".[dev,docs]" -e ./adapters/hermes_agent

git add -A
git status   # review; evidence PNGs are synthetic and safe
# ask agent to commit, or:
git commit -m "$(cat <<'EOF'
Rename product to Domain Foundry.

Provisional public name; keep availability/trademark checks before publish.
EOF
)"
git push -u origin HEAD
```

After the clean commit, create the exact machine candidate and pending reviewer
handoff. Do not fill or seal a review on a dirty candidate:

```bash
scripts/candidate_gate.sh
python scripts/review_packet.py prepare
```

### 3. External security pass

Hand [`docs/security.md`](security.md) + API surface to an independent reviewer.
Focus: localhost bind default, bearer on non-local, path/SQL safety, no tool
execution from captured text. File findings privately via SECURITY.md path.

### 4. Founder-as-user-0 (private — you only)

Follow [`FOUNDER_VALIDATION.md`](FOUNDER_VALIDATION.md) on a **production
install**, not this demo workspace:

```bash
pipx install domain-foundry-core   # after PyPI publish
# or from this checkout: pipx install .
domain-foundry init
```

Do **≥2 real private domains**, ≥10 real captures each, ≥3 corrections, ≥1
hardening migration. File friction as GitHub issues with **synthetic repros
only**. Never commit personal packs/data (`scripts/leakscan.py` is the backstop).

### 5. Demo GIF (90s — you record)

Against synthetic packs only:

1. Capture → routing badge in feed  
2. Open domain timeline  
3. One-message correction  

Save to `docs/assets/demo.gif`, uncomment the README image, re-run
`scripts/release_audit.sh` / leakscan, then commit.

Tools: QuickTime / Kap / `ffmpeg`. Do not fabricate a binary GIF.

### 6. Tag + PyPI + GitHub release

Prereqs: audit green, the exact-mark collision resolved, explicit publication
authority, and `build` + `twine` installed.

```bash
cd /path/to/domain_foundry
# Move CHANGELOG [0.1.0] out of "unreleased" if needed
git tag -a v0.1.0 -m "Domain Foundry v0.1.0"
python -m build
python -m twine upload --repository testpypi dist/*   # smoke first
pipx install --index-url https://test.pypi.org/simple/ domain-foundry-core
domain-foundry --help

python -m twine upload dist/*
( cd adapters/hermes_agent && python -m build && python -m twine upload dist/* )

git push origin v0.1.0
gh release create v0.1.0 --title "v0.1.0" --notes-file <(sed -n '/## \[0.1.0\]/,/## \[/p' CHANGELOG.md | head -n -1)
```

Optional docs: `mkdocs gh-deploy`.

### 7. Launch posts (drafts ready — post by hand)

Keep the first ~2 hours clear for replies. Order:

1. **Show HN** — [`docs/launch/show-hn.md`](launch/show-hn.md)  
2. **lobste.rs** — [`docs/launch/lobsters.md`](launch/lobsters.md)  
   (tags: `ai`, `databases`, `python`; mark `show`)  
3. **Nous** — [`docs/launch/nous.md`](launch/nous.md)  
4. **awesome-list PRs** — [`docs/launch/awesome-list-blurbs.md`](launch/awesome-list-blurbs.md)  
   (open PRs manually; do not auto-submit)

### 8. Hermes-agent live evidence (optional but good for Nous)

Contract tests cover the plugin; for a live screenshot:

```bash
domain-foundry serve   # terminal 1
# terminal 2: install adapter into hermes-agent per adapters/hermes_agent/README.md
# Capture via agent chat → screenshot tool call + harness feed badge
```

---

## Friction noted during synthetic E2E (file if it reproduces for you)

- CLI `domain-foundry correct "that bake was 80% hydration not 75"` amended the
  **dining** entry instead of the sourdough bake (ambiguous “that bake” with
  multiple recent captures). Worth a `corrections` issue with a synthetic repro.
- Feed “Wrong?” → amend tab stays disabled until object fields are loaded from
  detail (move / mark-wrong still work). May be intentional; confirm UX.

---

## Quick verify commands

```bash
cd /path/to/domain_foundry
export PATH="$PWD/.venv/bin:$PATH"
scripts/release_audit.sh
scripts/quickstart_gate.sh
domain-foundry version   # → 0.1.0
```
