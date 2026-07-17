import { BUILTIN_BLOCKS } from "../blocks/registry";

// In-app developer docs: the custom-block side-load path (plan §9.3, P5).
export function Docs() {
  return (
    <div className="docs">
      <h2>Extending the app</h2>

      <section>
        <h3>Config-level remix (most users)</h3>
        <p>
          Rearrange views, choose blocks, and tune facets/measures in a pack’s <code>projections.yaml</code>.
          Adding a field to <code>schema.yaml</code> automatically makes it available to columns, facets, and
          measures — no code.
        </p>
      </section>

      <section>
        <h3>Built-in blocks</h3>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Block</th>
              <th>Data contract</th>
              <th>Scope</th>
            </tr>
          </thead>
          <tbody>
            {BUILTIN_BLOCKS.map((b) => (
              <tr key={b.id}>
                <td>
                  <code>{b.id}</code>
                </td>
                <td>{b.dataContract.join(", ")}</td>
                <td>{b.global ? "global surface" : "per-domain view"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h3>Custom block (React devs)</h3>
        <p>
          A custom block is a React component that receives <code>BlockProps</code>{" "}
          (<code>domain</code>, <code>view</code>, <code>data</code>, <code>onOpenDetail</code>,{" "}
          <code>onChanged</code>) and renders data served by <code>/api/blocks/&lt;view&gt;/data</code>.
          Ship it in-tree via <code>app/src/blocks/registry.ts</code>, or side-load a built bundle:
        </p>
        <ol className="docs-steps">
          <li>
            Build an ESM bundle that exports a <code>register(registerBlock)</code> function:
            <pre className="code">
{`// my-blocks.js  (built with the app's Vite config)
export function register(registerBlock) {
  registerBlock("gauge", GaugeBlock);
  return ["gauge"]; // ids you registered
}`}
            </pre>
          </li>
          <li>
            Drop it at <code>~/.domain_foundry/blocks/index.js</code>. The server exposes it read-only at{" "}
            <code>/custom-blocks/index.js</code>.
          </li>
          <li>
            Reference the block from a pack view: <code>{`{ id: gauge, block: gauge, object: bake }`}</code>.
          </li>
        </ol>
        <p className="callout">
          Custom blocks are <strong>trusted code</strong> — they run in your browser session with full app
          access. Only side-load bundles you wrote or audited.
        </p>
      </section>

      <section>
        <h3>Bespoke app (power users)</h3>
        <p>
          Everything here consumes the same read-only HTTP API. Point any external app at{" "}
          <code>/api/blocks/*</code>, <code>/api/query</code>, and <code>/api/objects/*</code>; mutate only
          through <code>/api/capture</code> and <code>/api/correct</code>.
        </p>
      </section>
    </div>
  );
}
