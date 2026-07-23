# Private pipeline retirement runbook

**Do not execute** until production mesh week is clean and `needs_review < 20`.
This is a checklist, not an automated script.

## Preconditions

- [ ] Mesh fast path + outbound enabled and stable for ≥7 days
- [ ] Japanese + food (and any other cutover domains) no longer hit private
  `classify.py`
- [ ] Foundry home is writer-of-record; private DBs opened RO only
- [ ] Vault + DB backups under `HermesWorkspace/backups/<phase>/`
- [ ] `domain-foundry mesh status` healthy; DLQ empty or understood

## Steps (manual)

1. **Confirm zero traffic** to `~/.hermes/plugins/logbook` for cutover domains
   (gateway logs / counters).
2. **Disable** the logbook plugin in hermes-agent gateway config (comment out
   or set enabled=false) — do not delete yet.
3. **Archive aside** (move, do not delete):
   - `~/.hermes/plugins/logbook/classify.py`
   - `~/.hermes/plugins/logbook/store.py`
   - `HermesWorkspace/lib/{interpret,apply,feed}` (if unused)
4. **Freeze** `logbook.sqlite` / `personal.sqlite` / `travel.sqlite` as
   read-only mirrors (chmod or mount RO).
5. **Gateway remains** channels + mesh fast path + outbound poller only.
6. **Grep gate:** no live imports of retired modules from the running gateway.
7. Append the cutover UTC timestamp + greps to
   `HermesWorkspace/docs/CONVERGENCE_LOG.md`.

## Rollback

1. Re-enable logbook plugin.
2. Restore archived files from the move location.
3. Flip domain routing back to private classify if needed.
4. Sources were never mutated in place during migration — RO imports stay safe.

## Out of scope for agents

Do **not** disable production plugins, rewrite launchd, or delete private DBs
from an automated session without an explicit human OK in-chat.
