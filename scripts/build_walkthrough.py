#!/usr/bin/env python3
"""Build the self-contained HTML launch walkthrough for Domain Foundry.

Embeds the live app screenshots (from docs/tutorial/snapshots/img/) and the
proof transcripts as inline data, producing one dependency-free HTML file that
can be published as an Artifact or opened directly.

    python scripts/build_walkthrough.py [OUTPUT.html]
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "docs" / "tutorial" / "snapshots" / "img"


def data_uri(name: str) -> str:
    raw = (IMG / name).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode()


HTML = r"""<main>
<style>
  :root {
    --ground: #F4F6F5; --card: #FFFFFF; --ink: #111917; --muted: #5B6B66;
    --line: #E1E7E4; --accent: #1B7A63; --accent-soft: #E3F1EC;
    --coral: #C7615A; --coral-soft: #F6E4E2;
    --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    --term-bg: #10201B; --term-ink: #D7E4DE;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --ground: #0E1512; --card: #15201C; --ink: #E7EDEA; --muted: #93A69E;
      --line: #24322D; --accent: #3FBE99; --accent-soft: #17332A;
      --coral: #E0897F; --coral-soft: #33211F; --term-bg: #0A140F; --term-ink: #CFe0D8;
    }
  }
  :root[data-theme="light"] {
    --ground: #F4F6F5; --card: #FFFFFF; --ink: #111917; --muted: #5B6B66;
    --line: #E1E7E4; --accent: #1B7A63; --accent-soft: #E3F1EC;
    --coral: #C7615A; --coral-soft: #F6E4E2; --term-bg: #10201B; --term-ink: #D7E4DE;
  }
  :root[data-theme="dark"] {
    --ground: #0E1512; --card: #15201C; --ink: #E7EDEA; --muted: #93A69E;
    --line: #24322D; --accent: #3FBE99; --accent-soft: #17332A;
    --coral: #E0897F; --coral-soft: #33211F; --term-bg: #0A140F; --term-ink: #CFe0D8;
  }
  * { box-sizing: border-box; }
  main { background: var(--ground); color: var(--ink); font-family: var(--sans);
    line-height: 1.6; margin: 0; -webkit-font-smoothing: antialiased; }
  .wrap { max-width: 1000px; margin: 0 auto; padding: 0 24px; }
  .eyebrow { font-family: var(--mono); font-size: 12px; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--accent); font-weight: 600; }
  h1, h2, h3 { text-wrap: balance; line-height: 1.1; letter-spacing: -0.02em; }
  a { color: var(--accent); }
  code, .mono { font-family: var(--mono); }

  /* top bar */
  .bar { position: sticky; top: 0; z-index: 20; backdrop-filter: blur(10px);
    background: color-mix(in srgb, var(--ground) 82%, transparent);
    border-bottom: 1px solid var(--line); }
  .bar .wrap { display: flex; align-items: center; gap: 20px; height: 60px; }
  .brand { font-weight: 700; letter-spacing: -0.02em; display: flex; align-items: center; gap: 8px; }
  .brand .mark { color: var(--accent); font-size: 15px; }
  .bar nav { margin-left: auto; display: flex; gap: 22px; align-items: center; }
  .bar nav a { color: var(--muted); text-decoration: none; font-size: 14px; }
  .bar nav a:hover { color: var(--ink); }
  .toggle { font-family: var(--mono); font-size: 12px; border: 1px solid var(--line);
    background: var(--card); color: var(--muted); border-radius: 999px; padding: 5px 12px;
    cursor: pointer; }
  .toggle:hover { color: var(--ink); border-color: var(--accent); }

  /* hero */
  .hero { padding: 76px 0 40px; }
  .hero h1 { font-size: clamp(38px, 6vw, 62px); font-weight: 800; margin: 16px 0 0; }
  .hero .lede { font-size: clamp(17px, 2.2vw, 21px); color: var(--muted); max-width: 60ch; margin: 20px 0 0; }
  .cast { margin: 34px 0 8px; display: grid; grid-template-columns: 1fr auto 1fr; gap: 16px;
    align-items: center; max-width: 720px; }
  .cast .raw, .cast .rec { border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px;
    background: var(--card); }
  .cast .raw { font-family: var(--mono); font-size: 14px; color: var(--ink); }
  .cast .arrow { font-family: var(--mono); color: var(--accent); font-size: 22px; text-align: center; }
  .cast .rec .rk { font-family: var(--mono); font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.12em; color: var(--muted); }
  .cast .rec .rv { font-weight: 700; margin-top: 4px; }
  .pill { display: inline-flex; align-items: center; gap: 6px; font-family: var(--mono);
    font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 999px; margin-top: 10px; }
  .pill.ok { background: var(--accent-soft); color: var(--accent); }
  .ctas { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 30px; }
  .btn { font-weight: 600; text-decoration: none; border-radius: 10px; padding: 12px 20px; font-size: 15px; }
  .btn.primary { background: var(--accent); color: #fff; }
  .btn.primary:hover { filter: brightness(1.06); }
  .btn.ghost { border: 1px solid var(--line); color: var(--ink); background: var(--card); }
  .btn.ghost:hover { border-color: var(--accent); }

  /* section scaffolding */
  section { padding: 54px 0; border-top: 1px solid var(--line); }
  .sec-h { font-size: clamp(24px, 3.4vw, 34px); font-weight: 800; margin: 8px 0 0; }
  .sec-sub { color: var(--muted); max-width: 62ch; margin: 14px 0 0; }

  /* browser frame + proof shot */
  .frame { margin-top: 30px; border: 1px solid var(--line); border-radius: 14px; overflow: hidden;
    background: var(--card); box-shadow: 0 24px 60px -30px rgba(0,0,0,0.28); }
  .frame .chrome { display: flex; align-items: center; gap: 8px; padding: 11px 14px;
    border-bottom: 1px solid var(--line); background: color-mix(in srgb, var(--card) 88%, var(--ground)); }
  .frame .dot { width: 11px; height: 11px; border-radius: 50%; background: var(--line); }
  .frame .addr { font-family: var(--mono); font-size: 12px; color: var(--muted); margin-left: 8px; }
  .frame img { display: block; width: 100%; height: auto; }
  .caption { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 16px; font-size: 14px; color: var(--muted); }
  .caption b { color: var(--ink); font-weight: 600; }
  .tag { font-family: var(--mono); font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 6px; }
  .tag.ok { background: var(--accent-soft); color: var(--accent); }
  .tag.unf { background: var(--coral-soft); color: var(--coral); }

  /* harness tabs */
  .tabs { display: flex; gap: 8px; margin-top: 26px; flex-wrap: wrap; }
  .tab { font-family: var(--sans); font-size: 14px; font-weight: 600; cursor: pointer;
    border: 1px solid var(--line); background: var(--card); color: var(--muted);
    padding: 9px 16px; border-radius: 999px; display: inline-flex; align-items: center; gap: 8px; }
  .tab[aria-selected="true"] { color: #fff; background: var(--accent); border-color: var(--accent); }
  .tab .badge { font-family: var(--mono); font-size: 10px; opacity: 0.8; }
  .panel { margin-top: 18px; }
  .panel[hidden] { display: none; }
  .panel .desc { color: var(--muted); font-size: 15px; margin: 0 0 14px; max-width: 62ch; }
  .term { background: var(--term-bg); color: var(--term-ink); border-radius: 12px; padding: 18px 20px;
    font-family: var(--mono); font-size: 13px; line-height: 1.75; overflow-x: auto; border: 1px solid var(--line); }
  .term .c-key { color: #7fd4b8; }
  .term .c-you { color: #9ecbff; }
  .term .c-dim { color: #7f958c; }
  .proof-note { font-family: var(--mono); font-size: 12px; color: var(--muted); margin-top: 12px; }
  .proof-note b { color: var(--accent); }

  /* how it works */
  .steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 18px; margin-top: 28px; }
  .step { border: 1px solid var(--line); border-radius: 14px; padding: 20px; background: var(--card); }
  .step .n { font-family: var(--mono); font-size: 12px; color: var(--accent); font-weight: 700; }
  .step h3 { font-size: 17px; margin: 10px 0 6px; }
  .step p { color: var(--muted); font-size: 14px; margin: 0; }
  .split { display: grid; grid-template-columns: 1.1fr 1fr; gap: 28px; align-items: center; margin-top: 30px; }
  @media (max-width: 760px) { .split { grid-template-columns: 1fr; } .cast { grid-template-columns: 1fr; } .cast .arrow { transform: rotate(90deg); } }

  /* credibility + footer */
  .creds { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1px;
    background: var(--line); border: 1px solid var(--line); border-radius: 14px; overflow: hidden; margin-top: 8px; }
  .cred { background: var(--card); padding: 22px; }
  .cred .big { font-size: 26px; font-weight: 800; font-variant-numeric: tabular-nums; }
  .cred .lbl { font-family: var(--mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); margin-top: 4px; }
  footer { border-top: 1px solid var(--line); padding: 40px 0 60px; color: var(--muted); font-size: 14px; }
  footer .wrap { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }

  /* Content is always visible (no scroll-gating). Hero gets a single gentle
     load fade; everything else stays static and legible without JS. */
  .hero { animation: rise .7s ease both; }
  @keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
  @media (prefers-reduced-motion: reduce) { .hero { animation: none; } }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>

<div class="bar"><div class="wrap">
  <span class="brand"><span class="mark">&#9670;</span> Domain Foundry</span>
  <nav>
    <a href="#start">Get started</a>
    <a href="#harnesses">Harnesses</a>
    <a href="#how">How it works</a>
    <a href="https://github.com/finnqiao/domain_foundry">GitHub</a>
    <button class="toggle" id="tt" aria-label="Toggle theme">theme</button>
  </nav>
</div></div>

<header class="hero"><div class="wrap">
  <span class="eyebrow">Local-first &middot; MIT &middot; No telemetry</span>
  <h1>Speak it. It gets cast into data.</h1>
  <p class="lede">Domain Foundry turns what you say &mdash; in Claude Desktop, a Telegram chat, or
    your terminal &mdash; into permanent, structured, correctable records. In plain SQLite on your
    machine. You never fill in a form.</p>

  <div class="cast">
    <div class="raw">&ldquo;sent a tough V5 on the overhang today, crux was the heel hook&rdquo;</div>
    <div class="arrow">&rarr;</div>
    <div class="rec">
      <div class="rk">bouldering / entry</div>
      <div class="rv">V5 on the overhang</div>
      <span class="pill ok">&#9679; applied &middot; 95%</span>
    </div>
  </div>

  <div class="ctas">
    <a class="btn primary" href="#start">Get started</a>
    <a class="btn ghost" href="#harnesses">Connect your agent</a>
  </div>
</div></header>

<section id="proof"><div class="wrap reveal">
  <span class="eyebrow">The proof</span>
  <h2 class="sec-h">Captured first. Routed, never guessed.</h2>
  <p class="sec-sub">A real capture feed after five plain-language messages. Confident captures are
    filed; anything uncertain is kept as a card instead of being guessed at or dropped. Every row has
    a one-tap correction.</p>
  <div class="frame">
    <div class="chrome"><span class="dot"></span><span class="dot"></span><span class="dot"></span>
      <span class="addr">127.0.0.1:8787 &mdash; Domain Foundry</span></div>
    <img alt="Domain Foundry capture feed: five bouldering messages, each with a routing badge and a Wrong? button" src="__CAPTURE_FEED__">
  </div>
  <div class="caption">
    <span><span class="tag ok">applied &middot; 95%</span> &nbsp;<b>filed</b> to the bouldering domain.</span>
    <span><span class="tag unf">unfiled &middot; 20%</span> &nbsp;<b>kept</b>, not guessed &mdash; teach it and it routes next time.</span>
    <span><b>Wrong?</b> &mdash; one message fixes the record and becomes a regression test.</span>
  </div>
</div></section>

<section id="harnesses"><div class="wrap reveal">
  <span class="eyebrow">Three tested harnesses</span>
  <h2 class="sec-h">Talk to it from wherever you already are.</h2>
  <p class="sec-sub">The same local harness, three front-ends &mdash; each driven through the full loop
    (create a domain &rarr; capture &rarr; query &rarr; correct) by an automated end-to-end test in CI.
    The transcripts below are the actual proof output.</p>

  <div class="tabs" role="tablist" id="tablist">
    <button class="tab" role="tab" aria-selected="true" data-p="mcp">MCP <span class="badge">Claude Desktop / Cursor</span></button>
    <button class="tab" role="tab" aria-selected="false" data-p="tg">Telegram <span class="badge">text a bot</span></button>
    <button class="tab" role="tab" aria-selected="false" data-p="hz">hermes-agent <span class="badge">runtime</span></button>
  </div>

  <div class="panel" id="p-mcp" role="tabpanel">
    <p class="desc">One MCP server &rarr; every MCP client. Add a config block to Claude Desktop and
      just talk; the model calls the tools with capture-first discipline.</p>
    <div class="term"><span class="c-dim"># driven over real stdio MCP tools/call, exactly as a client does</span>
&#9656; new_domain(&quot;track my bouldering sessions&quot;)   <span class="c-key">&rarr; fork (atlas neighborhood)</span>
&#9656; wizard_reply(&quot;skip&quot;)   <span class="c-key">&rarr; bouldering</span>
&#9656; capture(&quot;good bouldering session, felt strong&quot;)
   <span class="c-key">{ status: &quot;applied&quot;, domain: &quot;bouldering&quot;, confidence: 0.95 }</span>
&#9656; correct(&quot;actually the rating was moderate not hard&quot;)
   <span class="c-key">{ action: &quot;amend&quot;, applied: true, eval_case: true }</span></div>
    <p class="proof-note">tested: <b>adapters/mcp/tests/test_mcp_e2e.py</b> &middot; install: <code>pipx install domain-foundry-mcp</code></p>
  </div>

  <div class="panel" id="p-tg" role="tabpanel" hidden>
    <p class="desc">Text a bot from your phone. Corrections work by just saying so. Nothing leaves your
      machine except the message to Telegram itself.</p>
    <div class="term"><span class="c-you">&#128100; /new track my bouldering climbing sessions</span>
&#129302; Sports &rarr; climbing. Ideas: session log, ticklist&hellip;
<span class="c-you">&#128100; skip</span>
&#129302; bouldering is ready. Send a real note and we&rsquo;ll file it.
<span class="c-you">&#128100; good bouldering session at the gym, felt strong</span>
&#129302; &#9989; Logged to bouldering (entry).
<span class="c-you">&#128100; actually the rating was moderate not hard</span>
&#129302; &#9997;&#65039; Corrected &mdash; and saved as a regression test.</div>
    <p class="proof-note">tested: <b>adapters/telegram/tests/test_telegram_bridge.py</b> &middot; install: <code>pipx install domain-foundry-telegram</code></p>
  </div>

  <div class="panel" id="p-hz" role="tabpanel" hidden>
    <p class="desc">A hermes-agent plugin that registers the harness tools with capture-first guidance
      and drives the in-process client &mdash; no HTTP hop, no server to keep alive.</p>
    <div class="term"><span class="c-dim"># the adapter's real tool surface, the exact surface hermes-agent invokes</span>
&#9656; domain_foundry_new_domain(goal_text=&quot;track my bouldering&#8230;&quot;)  <span class="c-key">&rarr; fork</span>
&#9656; domain_foundry_wizard_reply(&quot;skip&quot;)  <span class="c-key">&rarr; bouldering</span>
&#9656; domain_foundry_capture(&quot;good bouldering session&#8230;&quot;)
   <span class="c-key">status: applied &middot; domain: bouldering</span>
&#9656; domain_foundry_correct(&quot;actually the rating was moderate&#8230;&quot;)
   <span class="c-key">applied: true &middot; eval_case_id: ec_&#8230;</span></div>
    <p class="proof-note">tested: <b>adapters/hermes_agent/tests/test_hermes_e2e.py</b> &middot; regenerate all: <code>python scripts/tutorial_snapshots.py</code></p>
  </div>
</div></section>

<section id="how"><div class="wrap reveal">
  <span class="eyebrow">How it works</span>
  <h2 class="sec-h">A courier for your words &mdash; not the source of truth.</h2>
  <div class="steps">
    <div class="step"><div class="n">01</div><h3>Capture first</h3><p>Your exact words land in an append-only ledger before anything interprets them. Nothing is silently dropped.</p></div>
    <div class="step"><div class="n">02</div><h3>Routed, not guessed</h3><p>A typed record is created only when confident; otherwise it waits as a review or unfiled card.</p></div>
    <div class="step"><div class="n">03</div><h3>One-message corrections</h3><p>A plain sentence amends the record, keeps history, and compiles into a replayable regression test.</p></div>
    <div class="step"><div class="n">04</div><h3>Local SQLite</h3><p>Everything lives in files on your machine. No cloud, no vector soup, no telemetry &mdash; open it with any SQLite browser.</p></div>
  </div>

  <div class="split">
    <div>
      <span class="eyebrow">Fix it in one sentence</span>
      <h3 class="sec-h" style="font-size:22px">&ldquo;Actually that was a V6.&rdquo;</h3>
      <p class="sec-sub">Amend, move, merge, or undo &mdash; the canonical record changes, the history is
        preserved, and the correction becomes a permanent test so the same mistake can&rsquo;t come back.</p>
    </div>
    <div class="frame">
      <div class="chrome"><span class="dot"></span><span class="dot"></span><span class="dot"></span>
        <span class="addr">correct</span></div>
      <img alt="Correction dialog: amend, move, merge, undo, mark wrong" src="__CORRECTION__">
    </div>
  </div>
</div></section>

<section id="start"><div class="wrap reveal">
  <span class="eyebrow">Get started</span>
  <h2 class="sec-h">One install. Then talk to it.</h2>
  <div class="split" style="align-items:start">
    <div>
      <h3 style="font-size:17px; margin:18px 0 8px">Claude Desktop</h3>
      <div class="term"><span class="c-dim">$</span> pipx install domain-foundry-core domain-foundry-mcp
<span class="c-dim"># add to Settings &rarr; Developer &rarr; Edit Config:</span>
{ &quot;mcpServers&quot;: { &quot;domain-foundry&quot;: {
    &quot;command&quot;: &quot;domain-foundry-mcp&quot; } } }</div>
    </div>
    <div>
      <h3 style="font-size:17px; margin:18px 0 8px">Terminal</h3>
      <div class="term"><span class="c-dim">$</span> pipx install domain-foundry-core
<span class="c-dim">$</span> domain-foundry init
<span class="c-dim">$</span> domain-foundry new-domain &quot;track my bouldering&quot; --reply skip
<span class="c-dim">$</span> domain-foundry capture &quot;great session, felt strong&quot;</div>
    </div>
  </div>
  <div class="ctas">
    <a class="btn primary" href="https://github.com/finnqiao/domain_foundry">Read the docs</a>
    <a class="btn ghost" href="https://github.com/finnqiao/domain_foundry/tree/main/adapters">Browse the adapters</a>
  </div>
</div></section>

<section id="creds"><div class="wrap reveal">
  <div class="creds">
    <div class="cred"><div class="big">214</div><div class="lbl">tests green</div></div>
    <div class="cred"><div class="big">3</div><div class="lbl">tested harnesses</div></div>
    <div class="cred"><div class="big">100%</div><div class="lbl">local &middot; no telemetry</div></div>
    <div class="cred"><div class="big">MIT</div><div class="lbl">forever</div></div>
  </div>
</div></section>

<footer><div class="wrap">
  <span class="brand"><span class="mark">&#9670;</span> Domain Foundry</span>
  <span>Describe your passion. Get an app. Talk to it.</span>
  <span style="margin-left:auto"><a href="https://github.com/finnqiao/domain_foundry">github.com/finnqiao/domain_foundry</a></span>
</div></footer>

<script>
  (function () {
    var tt = document.getElementById('tt');
    tt && tt.addEventListener('click', function () {
      var cur = document.documentElement.getAttribute('data-theme');
      var next = cur === 'dark' ? 'light' : (cur === 'light' ? 'dark' :
        (matchMedia('(prefers-color-scheme: dark)').matches ? 'light' : 'dark'));
      document.documentElement.setAttribute('data-theme', next);
    });
    var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab'));
    function sel(id) {
      tabs.forEach(function (t) {
        var on = t.getAttribute('data-p') === id;
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        document.getElementById('p-' + t.getAttribute('data-p')).hidden = !on;
      });
    }
    tabs.forEach(function (t) { t.addEventListener('click', function () { sel(t.getAttribute('data-p')); }); });
  })();
</script>
</main>"""


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "tutorial" / "walkthrough.html"
    html = (HTML
            .replace("__CAPTURE_FEED__", data_uri("capture_feed.png"))
            .replace("__CORRECTION__", data_uri("correction.png")))
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
