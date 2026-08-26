# Telegram — snapshot

_The no-terminal track: text a bot, get structured data back._

```text
👤 /new i collect pokemon cards
🤖 You said “i collect pokemon cards”. You could:
1. Set completion: How close a set is, and which rares are still missing.
2. Collection dex: Identity, acquired-on, and a photo — a pokedex for objects.
3. Card dex (suggested): Each card you own, with a photo — binder pages you can search.
   a catalog you can page through · a gallery of the photos
4. Pull log: What came out of a pack, what you traded, and the condition.
Which of these, or say what you want it to do — a chart, photos, a mix board. Paste a notes folder path to ingest text. Photos: have your agent read them first, then send the text.

Reply with a number, an idea name, or describe the look (chart, photos, a field guide). I won't skip ahead.

👤 a dex of the cards i own with photos
🤖 Here is a look. Pick one, tell me how to change it (darker, denser, more chart), or say 'build it'.
1. Card dex (selected) — media_dex look (round 1)

👤 build it
🤖 🎉 *pokemon* is ready. Send me sample notes and I'll file them.

👤 pulled a holographic Charizard from a 151 booster, NM
🤖 ✅ Logged to *pokemon* (card).

👤 that Charizard was LP not NM
🤖 ✏️ Corrected — and saved as a regression test.

👤 /query pokemon
🤖 📚 *pokemon* — 1 shown:
• pulled a holographic Charizard from a 151 booster, NM

👤 /review
🤖 ✅ Nothing waiting for review.
```
