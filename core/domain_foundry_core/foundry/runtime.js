(() => {
  "use strict";

  const RUNTIME_SCHEMA_VERSION = 2;
  const MAX_RECORDS = 10000;
  const MAX_VISIBLE = 100;
  const MAX_BACKUP_BYTES = 10 * 1024 * 1024;
  const spec = JSON.parse(document.getElementById("foundry-spec").textContent);
  // What the compiler decided about this app's shape. The stylesheet already
  // carries the matching colours, type, density and layout.
  const plan = spec._render || {};
  const topology = plan.topology || spec.experience.navigation.topology;
  const signatures = plan.signature_elements || [];
  // In every layout but the session the rail sits beside the work, so it is a
  // complementary sidebar. In a session it runs across the top and holds the
  // app's name, so it is the banner.
  const railTag = topology === "session" ? "header" : "aside";
  const collapse = plan.collapse || {};
  const keyboard = plan.keyboard || {};
  const sources = new Map((spec._source_records || []).map((item) => [item.id, item]));
  const entityIds = new Set(spec.domain.entities.map((item) => item.id));
  const storageKey = `foundry-app:${spec.id}:v2`;
  const legacyStorageKey = `domain-foundry:${spec.id}:v1`;
  const selected = Object.create(null);
  let activeViewId = spec.experience.navigation.primary_view;
  let statusMessage = "";
  let errorMessage = "";

  const uid = () =>
    globalThis.crypto?.randomUUID?.() ||
    `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"]/g,
      (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char],
    );
  const label = (name) =>
    String(name).replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
  const entity = (id) => spec.domain.entities.find((item) => item.id === id);
  const view = () => spec.experience.views.find((item) => item.id === activeViewId);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const clean = (value) =>
    object(value)
      ? Object.fromEntries(
          Object.entries(value).filter(
            ([key]) => !["__proto__", "constructor", "prototype"].includes(key),
          ),
        )
      : {};

  function sanitizeRecord(entityId, value) {
    const allowed = new Set([
      ...entity(entityId).fields.map((field) => field.name),
      "object_uid",
      "captured_at",
      "updated_at",
      "_record_uid",
      "_version",
      "_supersedes",
      "_superseded_by",
    ]);
    return Object.fromEntries(
      Object.entries(clean(value)).filter(([key]) => allowed.has(key)),
    );
  }

  function sanitizeStore(value, strict = false) {
    const candidate = clean(value);
    if (strict && (!object(candidate.records) || !Array.isArray(candidate.receipts))) {
      throw new Error("Backup does not contain records and receipts.");
    }
    const records = Object.create(null);
    for (const entityId of entityIds) {
      const raw = candidate.records?.[entityId];
      if (raw === undefined) continue;
      if (!Array.isArray(raw)) {
        if (strict) throw new Error(`Records for ${entityId} must be an array.`);
        continue;
      }
      if (raw.length > MAX_RECORDS) {
        throw new Error(`Records for ${entityId} exceed the ${MAX_RECORDS} limit.`);
      }
      records[entityId] = raw.filter(object).map((item) => sanitizeRecord(entityId, item));
    }
    return {
      runtime_schema_version: RUNTIME_SCHEMA_VERSION,
      records,
      receipts: Array.isArray(candidate.receipts)
        ? candidate.receipts.slice(0, MAX_RECORDS * entityIds.size).map(clean)
        : [],
      sample_overrides: Object.fromEntries(
        Object.entries(clean(candidate.sample_overrides)).filter(
          ([key, target]) =>
            key.startsWith("sample:") && typeof target === "string" && target.length <= 240,
        ),
      ),
    };
  }

  const emptyStore = () =>
    sanitizeStore({ records: {}, receipts: [], sample_overrides: {} });
  let store = emptyStore();
  try {
    const current = localStorage.getItem(storageKey);
    const legacy = current === null ? localStorage.getItem(legacyStorageKey) : null;
    if (current || legacy) {
      store = sanitizeStore(JSON.parse(current || legacy));
      if (legacy) {
        statusMessage = "Earlier local records loaded; they migrate on the next save.";
      }
    }
  } catch {
    errorMessage =
      "Stored data could not be read. The app opened safely without changing that backup.";
  }

  // Colours, radius, type stack, density and topology are compiled into the
  // stylesheet and the body attributes, so the page is already correct before
  // this script runs.

  function sampleKey(entityId, record) {
    const identity = entity(entityId).identity.map((field) => record[field] ?? "").join("|");
    return `sample:${entityId}:${identity}`;
  }

  function recordKey(entityId, record, origin = "local") {
    return origin === "sample"
      ? sampleKey(entityId, record)
      : String(record._record_uid || record.object_uid || sampleKey(entityId, record));
  }

  function records(entityId, includeSuperseded = false) {
    const samples = (spec.domain.sample_records[entityId] || []).map((record) => ({
      ...record,
      __origin: "sample",
      __record_key: sampleKey(entityId, record),
    }));
    const local = (store.records[entityId] || []).map((record) => ({
      ...record,
      __origin: "local",
      __record_key: recordKey(entityId, record),
    }));
    if (includeSuperseded) return [...samples, ...local];
    return [
      ...samples.filter((record) => !store.sample_overrides[record.__record_key]),
      ...local.filter((record) => !record._superseded_by),
    ];
  }

  const stripContext = (record) =>
    Object.fromEntries(Object.entries(record).filter(([key]) => !key.startsWith("__")));
  const selectedRecord = (entityId) => {
    const items = records(entityId);
    return (
      items.find((item) => item.__record_key === selected[entityId]) ||
      items.at(-1) ||
      null
    );
  };
  const primaryValue = (record, entitySpec) => {
    const field = [
      "name",
      "title",
      "expression",
      "cue",
      "kind",
      ...entitySpec.identity,
    ].find((name) => record[name] !== undefined);
    return field ? record[field] : entitySpec.title;
  };
  const valueText = (value) =>
    value === null || value === undefined || value === ""
      ? "—"
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value);
  const fieldsFor = (record, entitySpec, limit = 5) =>
    entitySpec.fields
      .filter((field) => record[field.name] !== undefined)
      .slice(0, limit);

  function details(record, entitySpec, limit = 8) {
    return `<dl class="detail-grid">${fieldsFor(record, entitySpec, limit)
      .map(
        (field) =>
          `<dt>${esc(label(field.name))}</dt><dd>${esc(valueText(record[field.name]))}${
            field.unit ? ` <span class="measure">${esc(field.unit)}</span>` : ""
          }</dd>`,
      )
      .join("")}</dl>`;
  }

  function recordItem(record, entitySpec) {
    const isSelected = selected[entitySpec.id] === record.__record_key;
    return `<li class="record"><button class="record-select" type="button" data-record="${esc(
      record.__record_key,
    )}" data-entity="${esc(entitySpec.id)}" aria-pressed="${isSelected}"><strong>${esc(
      primaryValue(record, entitySpec),
    )}</strong></button>${details(record, entitySpec)}</li>`;
  }

  const empty = (entitySpec) =>
    `<div class="empty-state"><strong>No ${esc(
      entitySpec.title.toLowerCase(),
    )} yet</strong><p>${esc(entitySpec.description)}</p></div>`;
  const temporalField = (entitySpec) =>
    entitySpec.fields.find((field) => ["datetime", "date"].includes(field.type)) ||
    entitySpec.fields.find((field) => /(?:_at|_on|date|time)$/.test(field.name));
  const formattedDate = (value) => {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.valueOf())) return valueText(value);
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: String(value).includes("T") ? "short" : undefined,
    }).format(parsed);
  };

  function timeline(items, entitySpec) {
    const temporal = temporalField(entitySpec);
    const ordered = [...items].sort((left, right) => {
      const a = Date.parse(left[temporal?.name] || left.captured_at || "") || 0;
      const b = Date.parse(right[temporal?.name] || right.captured_at || "") || 0;
      return b - a;
    });
    return `<ol class="record-list timeline">${ordered
      .slice(0, MAX_VISIBLE)
      .map((record) => {
        const raw = temporal ? record[temporal.name] : record.captured_at;
        const time = raw
          ? `<time datetime="${esc(raw)}">${esc(formattedDate(raw))}</time>`
          : "";
        return recordItem(record, entitySpec).replace(
          '<li class="record">',
          `<li class="record">${time}`,
        );
      })
      .join("")}</ol>`;
  }

  function chart(items, entitySpec, region) {
    const numeric = entitySpec.fields.find((field) =>
      ["integer", "number", "duration"].includes(field.type),
    );
    if (!numeric) {
      return `<div class="explanation"><strong>${esc(
        region.title,
      )}</strong><p>No numeric measure is declared. Records remain visible without fabricating a metric.</p></div>`;
    }
    const points = items
      .map((record) => ({ record, value: Number(record[numeric.name]) }))
      .filter((point) => Number.isFinite(point.value))
      .slice(-MAX_VISIBLE);
    if (!points.length) return empty(entitySpec);
    const width = 640;
    const height = 250;
    const pad = 32;
    const minimum = Math.min(...points.map((point) => point.value));
    const maximum = Math.max(...points.map((point) => point.value));
    const range = maximum - minimum || 1;
    const positioned = points.map((point, index) => ({
      ...point,
      x:
        points.length === 1
          ? width / 2
          : pad + (index / (points.length - 1)) * (width - pad * 2),
      y: height - pad - ((point.value - minimum) / range) * (height - pad * 2),
    }));
    const path = positioned
      .map((point, index) => `${index ? "L" : "M"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`)
      .join(" ");
    const area = `${path} L ${positioned.at(-1).x.toFixed(1)} ${height - pad} L ${positioned[0].x.toFixed(1)} ${height - pad} Z`;
    const titleId = `chart-title-${region.id}`;
    return `<figure class="chart-figure"><svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="${esc(
      titleId,
    )}"><title id="${esc(titleId)}">${esc(region.title)}: ${esc(
      label(numeric.name),
    )} from ${esc(minimum)} to ${esc(maximum)}</title><line class="chart-grid" x1="${pad}" y1="${
      height - pad
    }" x2="${width - pad}" y2="${height - pad}"></line><path class="chart-area" d="${area}"></path><path class="chart-line" d="${path}"></path>${positioned
      .map(
        (point) =>
          `<circle class="chart-point" cx="${point.x}" cy="${point.y}" r="5"><title>${esc(
            primaryValue(point.record, entitySpec),
          )}: ${esc(point.value)}${numeric.unit ? ` ${esc(numeric.unit)}` : ""}</title></circle>`,
      )
      .join("")}</svg><figcaption>${esc(label(numeric.name))}${
      numeric.unit ? ` in ${esc(numeric.unit)}` : ""
    } · ${points.length} observed ${points.length === 1 ? "record" : "records"}; no invented interpolation.</figcaption></figure>`;
  }

  function table(items, entitySpec) {
    const fields = entitySpec.fields
      .filter((field) => items.some((record) => record[field.name] !== undefined))
      .slice(0, 5);
    if (!items.length || !fields.length) return empty(entitySpec);
    return `<div class="data-table-wrap"><table class="data-table"><thead><tr>${fields
      .map((field) => `<th scope="col">${esc(label(field.name))}</th>`)
      .join("")}</tr></thead><tbody>${items
      .slice(0, MAX_VISIBLE)
      .map((record) => {
        const isSelected = selected[entitySpec.id] === record.__record_key;
        return `<tr aria-selected="${isSelected}">${fields
          .map((field, index) => {
            const content = `${esc(valueText(record[field.name]))}${
              field.unit ? ` <span class="measure">${esc(field.unit)}</span>` : ""
            }`;
            return index === 0
              ? `<td><button class="record-select" type="button" data-record="${esc(
                  record.__record_key,
                )}" data-entity="${esc(
                  entitySpec.id,
                )}" aria-pressed="${isSelected}">${content}</button></td>`
              : `<td>${content}</td>`;
          })
          .join("")}</tr>`;
      })
      .join("")}</tbody></table></div>`;
  }

  function canvas(items, entitySpec) {
    const slots = items.slice(0, MAX_VISIBLE).map((record, index) => {
      const isSelected = selected[entitySpec.id] === record.__record_key;
      return `<button class="slot" type="button" data-record="${esc(
        record.__record_key,
      )}" data-entity="${esc(entitySpec.id)}" aria-pressed="${isSelected}"><span class="slot-number">${esc(
        record.collector_number || String(index + 1).padStart(3, "0"),
      )}</span><strong>${esc(primaryValue(record, entitySpec))}</strong></button>`;
    });
    while (slots.length < 8) {
      slots.push(
        `<div class="slot empty"><span class="slot-number">${String(
          slots.length + 1,
        ).padStart(3, "0")}</span><span>Open position</span></div>`,
      );
    }
    return `<div class="canvas-grid">${slots.join("")}</div>`;
  }

  function shelf(items, entitySpec) {
    if (!items.length) return empty(entitySpec);
    return `<div class="shelf-grid">${items
      .slice(0, MAX_VISIBLE)
      .map((record) => {
        const isSelected = selected[entitySpec.id] === record.__record_key;
        const secondary = fieldsFor(record, entitySpec, 3)
          .slice(1)
          .map((field) => valueText(record[field.name]))
          .filter((value) => value !== "—")
          .join(" · ");
        return `<button class="shelf-item" type="button" data-record="${esc(
          record.__record_key,
        )}" data-entity="${esc(entitySpec.id)}" aria-pressed="${isSelected}"><strong>${esc(
          primaryValue(record, entitySpec),
        )}</strong>${secondary ? `<small>${esc(secondary)}</small>` : ""}</button>`;
      })
      .join("")}</div>`;
  }

  function inspector(items, entitySpec) {
    const record = selectedRecord(entitySpec.id) || items[0];
    if (!record) return empty(entitySpec);
    return `<div class="explanation"><strong>${esc(
      primaryValue(record, entitySpec),
    )}</strong>${details(
      record,
      entitySpec,
      12,
    )}<p class="storage-note">Select a record before using an update or correction action.</p></div>`;
  }

  function workbench(items, entitySpec) {
    if (!items.length) return empty(entitySpec);
    const current = selectedRecord(entitySpec.id) || items[0];
    return `<div class="workbench"><aside><ul class="record-list">${items
      .slice(0, 12)
      .map((record) => recordItem(record, entitySpec))
      .join("")}</ul></aside><div><strong>${esc(
      primaryValue(current, entitySpec),
    )}</strong>${details(
      current,
      entitySpec,
      12,
    )}<p class="storage-note">Choose a record, then use the view action to create an immutable revision.</p></div></div>`;
  }

  function session(items, entitySpec, region) {
    const record = selectedRecord(entitySpec.id) || items[0];
    if (!record) return empty(entitySpec);
    const answerId = `session-answer-${region.id}`;
    return `<div class="session-card"><div><div class="cue">${esc(
      record.cue || primaryValue(record, entitySpec),
    )}</div><button class="button" data-reveal="${esc(
      answerId,
    )}" type="button">Reveal answer</button><p class="session-answer" id="${esc(
      answerId,
    )}" hidden>${esc(record.answer || "Review the source context")}</p></div></div>`;
  }

  function explanation(region) {
    const workload = spec.domain.workloads.find((item) => item.id === region.workload_id);
    return `<div class="explanation"><strong>${esc(
      workload?.question || region.title,
    )}</strong><p>${esc(
      workload?.acceptance || "This region is derived from a declared user workload.",
    )}</p><p class="storage-note">Expected scale: ${esc(
      workload?.expected_scale || "not specified",
    )} · ${esc(label(workload?.kind || "read"))}</p></div>`;
  }

  function region(regionSpec) {
    const entitySpec = entity(regionSpec.entity);
    const items = records(regionSpec.entity);
    let content;
    switch (regionSpec.kind) {
      case "canvas":
        content = canvas(items, entitySpec);
        break;
      case "session":
        content = session(items, entitySpec, regionSpec);
        break;
      case "chart":
        content = chart(items, entitySpec, regionSpec);
        break;
      case "timeline":
        content = items.length ? timeline(items, entitySpec) : empty(entitySpec);
        break;
      case "comparison":
      case "table":
      case "ledger":
        content = table(items, entitySpec);
        break;
      case "shelf":
      case "catalog":
      case "media":
        content = shelf(items, entitySpec);
        break;
      case "inspector":
        content = inspector(items, entitySpec);
        break;
      case "workbench":
        content = workbench(items, entitySpec);
        break;
      case "explanation":
        content = explanation(regionSpec);
        break;
      default:
        content = items.length
          ? `<ul class="record-list">${items
              .slice(0, MAX_VISIBLE)
              .map((record) => recordItem(record, entitySpec))
              .join("")}</ul>`
          : empty(entitySpec);
    }
    const clipped =
      items.length > MAX_VISIBLE
        ? `<p class="storage-note">Showing ${MAX_VISIBLE} of ${items.length} records. Complete history remains in export.</p>`
        : "";
    const narrow = collapse[`${activeViewId}:${regionSpec.id}`] || {};
    const paged = narrow.paged ? ' data-narrow="paged"' : "";
    return `<section class="region ${esc(regionSpec.emphasis)} kind-${esc(
      regionSpec.kind,
    )}" data-region-kind="${esc(regionSpec.kind)}" data-region-emphasis="${esc(
      regionSpec.emphasis,
    )}" style="--span:${regionSpec.span};--collapse-order:${Number(
      narrow.order ?? 50,
    )}"${paged} aria-labelledby="region-${esc(
      regionSpec.id,
    )}"><h3 id="region-${esc(regionSpec.id)}">${esc(
      regionSpec.title,
    )}</h3><p class="region-meta">${esc(label(regionSpec.kind))} · ${esc(
      entitySpec.title,
    )}</p>${content}${clipped}</section>`;
  }

  // --- Signature elements -------------------------------------------------
  // One renderer per motif the spec asked for. Each reads declared data. When
  // the data it needs is not in this app, it says so instead of inventing it.

  const signatureNote = (title, message, className) =>
    `<section class="signature ${className}"><h2>${esc(title)}</h2><p class="signature-note">${esc(
      message,
    )}</p></section>`;

  function signatureEntity() {
    const current = view();
    const first = current.regions[0];
    return entity(first.entity);
  }

  function progressSignature() {
    const entitySpec = signatureEntity();
    const items = records(entitySpec.id);
    const enums = entitySpec.fields.filter(
      (field) => field.type === "enum" && (field.values || []).length > 1,
    );
    // A field that names a stage says more about progress than any enum.
    const stage =
      enums.find((field) => /phase|stage|status|state|step|progress|level/.test(field.name)) ||
      enums[0];
    const flag = /done|complete|finish|owned|caught|read/.test(
      entitySpec.fields.find((field) => field.type === "boolean")?.name || "",
    )
      ? entitySpec.fields.find((field) => field.type === "boolean")
      : stage
        ? null
        : entitySpec.fields.find((field) => field.type === "boolean");
    if (!items.length || (!flag && !stage)) {
      return signatureNote(
        "Progress",
        `This app does not declare a field that says when a ${entitySpec.title.toLowerCase()} is finished, so no progress is shown.`,
        "signature-progress",
      );
    }
    const target = flag ? flag.name : stage.name;
    const goal = flag ? true : stage.values[stage.values.length - 1];
    const done = items.filter((record) => record[target] === goal).length;
    const percent = Math.round((done / items.length) * 100);
    const text = flag
      ? `${done} of ${items.length} ${entitySpec.title.toLowerCase()} marked ${label(target)}`
      : `${done} of ${items.length} ${entitySpec.title.toLowerCase()} reached ${label(
          String(goal),
        )}`;
    return `<section class="signature signature-progress"><h2>Progress</h2><div class="bar" role="img" aria-label="${esc(
      `${text}, ${percent} percent`,
    )}"><span style="width:${percent}%"></span></div><p class="bar-label">${esc(text)}</p></section>`;
  }

  function lifeListSignature() {
    const entitySpec = signatureEntity();
    const items = records(entitySpec.id);
    if (!items.length) {
      return signatureNote(
        "Your list so far",
        `Nothing recorded yet. Add a ${entitySpec.title.toLowerCase()} and it appears here.`,
        "signature-life-list",
      );
    }
    const counts = new Map();
    for (const record of items) {
      const name = String(primaryValue(record, entitySpec));
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    const rows = [...counts.entries()].slice(0, 12);
    return `<section class="signature signature-life-list"><h2>Your list so far</h2><ol>${rows
      .map(
        ([name, count]) =>
          `<li><span>${esc(name)}</span><span class="count">${count}</span></li>`,
      )
      .join("")}</ol><p class="bar-label">${counts.size} different ${esc(
      entitySpec.title.toLowerCase(),
    )} recorded.</p></section>`;
  }

  function comparisonSignature() {
    const entitySpec = signatureEntity();
    const items = records(entitySpec.id);
    if (items.length < 2) {
      return signatureNote(
        "Side by side",
        `Two ${entitySpec.title.toLowerCase()} records are needed before this can compare anything.`,
        "signature-comparison",
      );
    }
    const [left, right] = items.slice(-2);
    const fields = entitySpec.fields
      .filter((field) => left[field.name] !== undefined || right[field.name] !== undefined)
      .slice(0, 6);
    const column = (record) =>
      `<div><strong>${esc(primaryValue(record, entitySpec))}</strong><dl class="detail-grid">${fields
        .map(
          (field) =>
            `<dt>${esc(label(field.name))}</dt><dd${
              valueText(left[field.name]) === valueText(right[field.name]) ? "" : ' class="changed"'
            }>${esc(valueText(record[field.name]))}</dd>`,
        )
        .join("")}</dl></div>`;
    return `<section class="signature signature-comparison"><h2>Side by side</h2><div class="pair">${column(
      left,
    )}${column(right)}</div><p class="bar-label">The two most recent ${esc(
      entitySpec.title.toLowerCase(),
    )} records. Values that differ are marked.</p></section>`;
  }

  function timelineSignature() {
    const entitySpec = signatureEntity();
    const items = records(entitySpec.id);
    const temporal = temporalField(entitySpec);
    if (!items.length || !temporal) {
      return signatureNote(
        "When things happened",
        `This app does not declare a date on ${entitySpec.title.toLowerCase()}, so there is nothing to lay out in time.`,
        "signature-timeline",
      );
    }
    const ordered = [...items]
      .sort(
        (a, b) =>
          (Date.parse(b[temporal.name] || "") || 0) - (Date.parse(a[temporal.name] || "") || 0),
      )
      .slice(0, 8);
    return `<section class="signature signature-timeline"><h2>When things happened</h2><ol>${ordered
      .map(
        (record) =>
          `<li><time datetime="${esc(record[temporal.name] || "")}">${esc(
            formattedDate(record[temporal.name]),
          )}</time><span>${esc(primaryValue(record, entitySpec))}</span></li>`,
      )
      .join("")}</ol></section>`;
  }

  function gapGridSignature() {
    const entitySpec = signatureEntity();
    const items = records(entitySpec.id);
    const counter = entitySpec.fields.find(
      (field) =>
        ["integer", "text"].includes(field.type) &&
        /number|position|index|slot|no$/.test(field.name),
    );
    const set = entitySpec.fields.find(
      (field) => field.type === "enum" && (field.values || []).length > 1,
    );
    if (counter) {
      const held = new Set(items.map((record) => String(record[counter.name])));
      const numbers = [...held]
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value));
      const highest = numbers.length ? Math.max(...numbers) : held.size;
      const cells = [];
      for (let index = 1; index <= Math.min(Math.max(highest, held.size), 60); index += 1) {
        const filled = held.has(String(index)) || held.has(String(index).padStart(3, "0"));
        cells.push(
          `<span class="cell${filled ? "" : " missing"}">${String(index).padStart(2, "0")}</span>`,
        );
      }
      return `<section class="signature signature-gap-grid"><h2>What you have and what is missing</h2><div class="cells">${cells.join(
        "",
      )}</div><p class="bar-label">${held.size} of ${cells.length} positions filled, by ${esc(
        label(counter.name),
      )}.</p></section>`;
    }
    if (set) {
      const held = new Set(items.map((record) => String(record[set.name])));
      return `<section class="signature signature-gap-grid"><h2>What you have and what is missing</h2><div class="cells">${(
        set.values || []
      )
        .map(
          (value) =>
            `<span class="cell${held.has(String(value)) ? "" : " missing"}">${esc(
              label(value),
            )}</span>`,
        )
        .join("")}</div><p class="bar-label">${held.size} of ${
        (set.values || []).length
      } ${esc(label(set.name))} values recorded.</p></section>`;
    }
    return signatureNote(
      "What you have and what is missing",
      `This app does not declare a numbered position or a fixed set on ${entitySpec.title.toLowerCase()}, so gaps cannot be shown.`,
      "signature-gap-grid",
    );
  }

  const SIGNATURE_RENDERERS = {
    progress_bar: progressSignature,
    life_list: lifeListSignature,
    comparison_strip: comparisonSignature,
    timeline_rail: timelineSignature,
    gap_grid: gapGridSignature,
  };
  const HEADER_SIGNATURES = ["progress_bar"];
  const PANEL_SIGNATURES = ["life_list", "timeline_rail"];

  const signatureGroup = (names) =>
    names
      .filter((name) => signatures.includes(name) && SIGNATURE_RENDERERS[name])
      .map((name) => SIGNATURE_RENDERERS[name]())
      .join("");

  // --- Topology -----------------------------------------------------------
  // Five layouts, five different arrangements of the same regions.

  function regionsShell(current) {
    const parts = current.regions.map(region);
    if (topology === "hub") {
      const cards = spec.experience.views
        .map(
          (item) =>
            `<button class="hub-card" type="button" data-view="${esc(item.id)}"${
              item.id === current.id ? ' aria-current="page"' : ""
            }><strong>${esc(item.title)}</strong><small>${esc(item.purpose)}</small></button>`,
        )
        .join("");
      return `<nav class="hub-overview" aria-label="Everything in this app">${cards}</nav><div class="regions">${parts.join(
        "",
      )}</div>`;
    }
    if (topology === "workflow") {
      return `<ol class="workflow-track">${current.regions
        .map(
          (item, index) =>
            `<li class="workflow-stage" data-stage="${index + 1}"><p class="workflow-step"><span class="workflow-index">${
              index + 1
            }</span>Step ${index + 1} of ${current.regions.length}</p>${parts[index]}</li>`,
        )
        .join("")}</ol>`;
    }
    if (topology === "split") {
      const detail =
        parts.slice(1).join("") ||
        `<div class="empty-state"><p>This view has one region, so there is nothing to show beside it.</p></div>`;
      return `<div class="split"><div class="split-index">${parts[0]}</div><div class="split-detail">${detail}</div></div>`;
    }
    if (topology === "canvas") {
      return `<div class="canvas-board">${current.regions
        .map(
          (item, index) =>
            `<div class="canvas-tile" style="--tile-span:${Math.max(
              2,
              Math.min(6, Math.round(item.span / 2)),
            )}"><span class="canvas-position">Position ${String(index + 1).padStart(
              2,
              "0",
            )}</span>${parts[index]}</div>`,
        )
        .join("")}</div>`;
    }
    return `<div class="session-stage">${parts.join("")}</div>`;
  }

  function viewBody(current) {
    const strip = signatureGroup(["comparison_strip", "gap_grid"]);
    const panel = signatureGroup(PANEL_SIGNATURES);
    const body = `${strip ? `<div class="signature-strip">${strip}</div>` : ""}${regionsShell(
      current,
    )}`;
    if (!panel) return body;
    return `<div class="with-signature-panel"><div>${body}</div><aside class="signature-panel" aria-label="Alongside this view">${panel}</aside></div>`;
  }

  function announce(message, isError = false) {
    statusMessage = isError ? "" : message;
    errorMessage = isError ? message : "";
    const status = document.getElementById("status");
    const error = document.getElementById("runtime-error");
    if (status) status.textContent = statusMessage;
    if (error) error.textContent = errorMessage;
  }

  function reveal(button) {
    const answer = document.getElementById(button.dataset.reveal);
    if (!answer) {
      announce("This view has no revealable answer.", true);
      return;
    }
    answer.hidden = false;
    button.disabled = true;
    announce("Answer revealed. No review outcome was recorded.");
  }

  function render() {
    const current = view();
    const primary = current.actions[0];
    const stored = Object.values(store.records).reduce(
      (total, items) => total + items.length,
      0,
    );
    document.getElementById("app").innerHTML = `<div class="app"><${railTag} class="rail"><div><h2 class="brand">${esc(
      spec.title,
    )}</h2><p class="world">${esc(spec.experience.visual_world.name)}<br>${esc(
      spec.experience.visual_world.mood,
    )}</p></div><nav class="view-nav" aria-label="Application views">${spec.experience.views
      .map(
        (item) =>
          `<button type="button" data-view="${esc(item.id)}" ${
            item.id === current.id ? 'aria-current="page"' : ""
          }>${esc(item.title)}</button>`,
      )
      .join("")}</nav><p class="rail-foot">Local application<br>Spec ${esc(
      spec.spec_version,
    )} · runtime ${RUNTIME_SCHEMA_VERSION}<br>${stored} owned ${
      stored === 1 ? "version" : "versions"
    }</p></${railTag}><main id="main" tabindex="-1"><header class="topbar"><div><h1>${esc(
      spec.title,
    )}</h1><p>${esc(
      spec.research.desired_outcome,
    )}</p>${signatureGroup(HEADER_SIGNATURES)}</div><div class="toolbar"><button class="button" id="evidence" type="button">Why this app</button><button class="button" id="export" type="button">Export backup</button><button class="button" id="restore" type="button">Restore backup</button><input class="visually-hidden" id="restore-file" type="file" accept="application/json,.json" aria-label="Choose JSON backup">${
      primary
        ? `<button class="button primary" id="primary-action" type="button" data-operation="${esc(
            primary.operation,
          )}">${esc(primary.label)}</button>`
        : ""
    }</div></header><section class="view-head" aria-labelledby="view-title"><h2 id="view-title">${esc(
      current.title,
    )}</h2><p>${esc(current.purpose)} ${esc(
      current.layout,
    )}</p></section>${viewBody(current)}<div class="view-actions">${current.actions
      .slice(1)
      .map(
        (action) =>
          `<button class="button" type="button" data-action="${esc(
            action.id,
          )}" data-operation="${esc(action.operation)}">${esc(action.label)}</button>`,
      )
      .join("")}</div><p class="status" id="status" tabindex="-1" role="status" aria-live="polite">${esc(
      statusMessage,
    )}</p><p class="error" id="runtime-error" role="alert">${esc(
      errorMessage,
    )}</p></main></div>`;

    document.querySelectorAll("[data-view]").forEach((button) =>
      button.addEventListener("click", () => {
        activeViewId = button.dataset.view;
        render();
        document.getElementById("main").focus();
      }),
    );
    document.querySelectorAll("[data-record]").forEach((button) =>
      button.addEventListener("click", () => {
        const entityId = button.dataset.entity;
        const recordId = button.dataset.record;
        selected[entityId] = recordId;
        render();
        [...document.querySelectorAll("[data-record]")]
          .find(
            (candidate) =>
              candidate.dataset.entity === entityId &&
              candidate.dataset.record === recordId,
          )
          ?.focus();
      }),
    );
    document.querySelectorAll("[data-reveal]").forEach((button) =>
      button.addEventListener("click", () => reveal(button)),
    );
    document
      .getElementById("primary-action")
      ?.addEventListener("click", () => runAction(primary));
    document.querySelectorAll("[data-action]").forEach((button) =>
      button.addEventListener("click", () =>
        runAction(current.actions.find((action) => action.id === button.dataset.action)),
      ),
    );
    document.getElementById("evidence").addEventListener("click", openEvidence);
    document.getElementById("export").addEventListener("click", exportData);
    document
      .getElementById("restore")
      .addEventListener("click", () => document.getElementById("restore-file").click());
    document.getElementById("restore-file").addEventListener("change", restoreData);
  }

  // --- Keyboard -----------------------------------------------------------
  // The spec's keyboard sentences, wired to real keys. Nothing here is on
  // unless the spec asked for it.

  function focusAfterCapture(entitySpec) {
    const mode = keyboard.focus_after_capture || "main";
    if (mode === "status") {
      document.getElementById("status")?.focus();
      return;
    }
    if (mode === "record") {
      const key = selected[entitySpec.id];
      const button = [...document.querySelectorAll("[data-record]")].find(
        (candidate) =>
          candidate.dataset.entity === entitySpec.id && candidate.dataset.record === key,
      );
      if (button) {
        button.focus();
        return;
      }
    }
    document.getElementById("main")?.focus();
  }

  function installKeyboard() {
    document.addEventListener("keydown", (event) => {
      const target = event.target;
      if (event.key === "Escape" && keyboard.escape_returns_to_main) {
        if (!document.querySelector("dialog[open]")) document.getElementById("main")?.focus();
        return;
      }
      if (event.key === " " && keyboard.space_reveals) {
        const onStage =
          target === document.body || (target instanceof Element && target.id === "main");
        const button = document.querySelector("[data-reveal]");
        if (onStage && button && !button.disabled) {
          event.preventDefault();
          reveal(button);
        }
        return;
      }
      if (
        keyboard.arrow_navigation &&
        ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)
      ) {
        const button = target instanceof Element ? target.closest("[data-record]") : null;
        if (!button) return;
        const scope = button.closest(".region") || document;
        const buttons = [...scope.querySelectorAll("[data-record]")];
        const step = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1;
        const next = buttons[buttons.indexOf(button) + step];
        if (next) {
          event.preventDefault();
          next.focus();
        }
      }
    });
  }

  function runAction(action) {
    if (!action) return;
    if (action.operation === "reveal") {
      const button = document.querySelector("[data-reveal]");
      if (button) reveal(button);
      else announce("This action has no revealable content in the current view.", true);
      return;
    }
    const revising = ["update", "correct"].includes(action.operation);
    const current = revising ? selectedRecord(action.entity) : null;
    if (revising && !current) {
      announce(
        `Add or select ${entity(action.entity).title.toLowerCase()} before ${action.label.toLowerCase()}.`,
        true,
      );
      return;
    }
    openCapture(action.entity, action, current);
  }

  function relationshipForField(entityId, fieldName) {
    return spec.domain.relationships.find((relationship) => {
      if (relationship.from_entity !== entityId) return false;
      const target = entity(relationship.to_entity);
      return [`${target.id}_id`, target.identity[0]].includes(fieldName);
    });
  }

  function controlValue(field, record) {
    const value = record?.[field.name];
    if (value === null || value === undefined) return "";
    if (field.type === "json") return JSON.stringify(value, null, 2);
    if (field.type === "datetime") return String(value).slice(0, 16);
    return String(value);
  }

  function inputFor(field, entitySpec, current) {
    const id = `field-${field.name}`;
    const helpId = `${id}-help`;
    const value = controlValue(field, current);
    const required = field.required ? " required" : "";
    const sensitive = field.sensitive ? ' autocomplete="off"' : "";
    const help = `<small id="${esc(helpId)}">${esc(field.description)}${
      field.unit ? ` · ${esc(field.unit)}` : ""
    }</small>`;
    const relationship = relationshipForField(entitySpec.id, field.name);
    if (relationship) {
      const target = entity(relationship.to_entity);
      const options = records(target.id)
        .map((record) => ({
          value: record[target.identity[0]],
          title: primaryValue(record, target),
        }))
        .filter((option) => option.value !== undefined);
      if (value && !options.some((option) => String(option.value) === value)) {
        options.unshift({ value, title: value });
      }
      return `<label for="${esc(id)}">${esc(label(field.name))}${help}<select id="${esc(
        id,
      )}" name="${esc(field.name)}" aria-describedby="${esc(helpId)}"${required}><option value="">Choose…</option>${options
        .map(
          (option) =>
            `<option value="${esc(option.value)}" ${
              String(option.value) === value ? "selected" : ""
            }>${esc(option.title)}</option>`,
        )
        .join("")}</select></label>`;
    }
    if (field.type === "enum") {
      return `<label for="${esc(id)}">${esc(label(field.name))}${help}<select id="${esc(
        id,
      )}" name="${esc(field.name)}" aria-describedby="${esc(helpId)}"${required}><option value="">Choose…</option>${(
        field.values || []
      )
        .map(
          (option) =>
            `<option value="${esc(option)}" ${
              String(option) === value ? "selected" : ""
            }>${esc(label(option))}</option>`,
        )
        .join("")}</select></label>`;
    }
    if (field.type === "boolean") {
      return `<label for="${esc(id)}">${esc(label(field.name))}${help}<select id="${esc(
        id,
      )}" name="${esc(field.name)}" aria-describedby="${esc(helpId)}"${required}><option value="">Not set</option><option value="true" ${
        value === "true" ? "selected" : ""
      }>Yes</option><option value="false" ${
        value === "false" ? "selected" : ""
      }>No</option></select></label>`;
    }
    const type = ["integer", "number", "duration"].includes(field.type)
      ? "number"
      : field.type === "date"
        ? "date"
        : field.type === "datetime"
          ? "datetime-local"
          : "text";
    const long =
      field.type === "json" ||
      /notes|method|context|answer|meaning|hypothesis|conclusion|description/.test(
        field.name,
      );
    const control = long
      ? `<textarea id="${esc(id)}" name="${esc(
          field.name,
        )}" aria-describedby="${esc(helpId)}" maxlength="2000"${required}${sensitive}>${esc(
          value,
        )}</textarea>`
      : `<input id="${esc(id)}" name="${esc(field.name)}" type="${type}" aria-describedby="${esc(
          helpId,
        )}"${type === "text" ? ' maxlength="2000"' : ""} value="${esc(
          value,
        )}"${required}${sensitive}${type === "number" ? ' step="any"' : ""}>`;
    return `<label for="${esc(id)}">${esc(label(field.name))}${help}${control}</label>`;
  }

  function parseField(field, raw) {
    if (raw === null || raw === "") return undefined;
    if (["integer", "number", "duration"].includes(field.type)) {
      const value = Number(raw);
      if (!Number.isFinite(value)) throw new Error(`${label(field.name)} must be a number.`);
      if (field.type === "integer" && !Number.isInteger(value)) {
        throw new Error(`${label(field.name)} must be a whole number.`);
      }
      return value;
    }
    if (field.type === "boolean") return raw === "true";
    if (field.type === "json") {
      try {
        return JSON.parse(raw);
      } catch {
        throw new Error(`${label(field.name)} must be valid JSON.`);
      }
    }
    return raw;
  }

  function comparison(left, operator, right) {
    if (operator === ">") return left > right;
    if (operator === ">=") return left >= right;
    if (operator === "<") return left < right;
    if (operator === "<=") return left <= right;
    if (["=", "=="].includes(operator)) return left === right;
    if (operator === "!=") return left !== right;
    return false;
  }

  function expressionValue(raw) {
    if (/^-?\d+(?:\.\d+)?$/.test(raw)) return Number(raw);
    if (/^'.*'$|^".*"$/.test(raw)) return raw.slice(1, -1);
    if (raw.toUpperCase() === "NULL") return null;
    throw new Error("unsupported comparison value");
  }

  function evaluateCheck(expression, record) {
    return expression.split(/\s+OR\s+/i).some((group) =>
      group.split(/\s+AND\s+/i).every((clause) => {
        const match = clause
          .trim()
          .match(
            /^([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|!=|==|=|>|<)\s*(-?\d+(?:\.\d+)?|'.*'|".*"|NULL)$/i,
          );
        if (!match) throw new Error("unsupported check expression");
        return comparison(record[match[1]], match[2], expressionValue(match[3]));
      }),
    );
  }

  function validateRecord(entitySpec, record, current) {
    const missing = entitySpec.fields
      .filter(
        (field) =>
          field.required &&
          (record[field.name] === undefined || record[field.name] === ""),
      )
      .map((field) => label(field.name));
    if (missing.length) {
      throw new Error(`Complete the required fields: ${missing.join(", ")}.`);
    }
    const uniqueSets = [
      entitySpec.identity,
      ...spec.domain.constraints
        .filter(
          (constraint) =>
            constraint.entity === entitySpec.id && constraint.kind === "unique",
        )
        .map((constraint) => constraint.fields),
    ];
    const peers = records(entitySpec.id).filter(
      (candidate) => candidate.__record_key !== current?.__record_key,
    );
    for (const fields of uniqueSets) {
      const duplicate = peers.some((candidate) =>
        fields.every(
          (field) =>
            candidate[field] !== undefined &&
            record[field] !== undefined &&
            String(candidate[field]) === String(record[field]),
        ),
      );
      if (duplicate) {
        throw new Error(
          `A ${entitySpec.title.toLowerCase()} with the same ${fields
            .map(label)
            .join(" and ")} already exists.`,
        );
      }
    }
    for (const constraint of spec.domain.constraints.filter(
      (item) =>
        item.entity === entitySpec.id && item.kind === "check" && item.expression,
    )) {
      let accepted;
      try {
        accepted = evaluateCheck(constraint.expression, record);
      } catch {
        throw new Error(
          `The app cannot safely evaluate “${constraint.reason}”. Rebuild with a supported declarative constraint.`,
        );
      }
      if (!accepted) throw new Error(constraint.reason);
    }
  }

  function validateBackup(next) {
    const activeByEntity = Object.create(null);
    for (const entityId of entityIds) {
      const entitySpec = entity(entityId);
      const imported = next.records[entityId] || [];
      for (const record of imported) {
        if (
          typeof record.object_uid !== "string" ||
          typeof record._record_uid !== "string" ||
          !Number.isInteger(record._version) ||
          record._version < 1
        ) {
          throw new Error(`${entitySpec.title} backup history lacks version identity.`);
        }
        for (const field of entitySpec.fields) {
          const value = record[field.name];
          if (field.required && (value === undefined || value === "")) {
            throw new Error(`${entitySpec.title} is missing ${label(field.name)}.`);
          }
          if (value === undefined || value === null) continue;
          if (field.type === "integer" && !Number.isInteger(value)) {
            throw new Error(`${label(field.name)} must be a whole number.`);
          }
          if (["number", "duration"].includes(field.type) && !Number.isFinite(value)) {
            throw new Error(`${label(field.name)} must be a number.`);
          }
          if (field.type === "boolean" && typeof value !== "boolean") {
            throw new Error(`${label(field.name)} must be true or false.`);
          }
          if (
            ["text", "date", "datetime", "enum", "attachment", "location"].includes(
              field.type,
            ) &&
            typeof value !== "string"
          ) {
            throw new Error(`${label(field.name)} must be text.`);
          }
          if (field.type === "enum" && !(field.values || []).includes(value)) {
            throw new Error(`${label(field.name)} has an unsupported value.`);
          }
        }
        for (const constraint of spec.domain.constraints.filter(
          (item) => item.entity === entityId && item.kind === "check" && item.expression,
        )) {
          if (!evaluateCheck(constraint.expression, record)) {
            throw new Error(constraint.reason);
          }
        }
      }
      const samples = (spec.domain.sample_records[entityId] || []).filter(
        (record) => !next.sample_overrides[sampleKey(entityId, record)],
      );
      activeByEntity[entityId] = [
        ...samples,
        ...imported.filter((record) => !record._superseded_by),
      ];
      const uniqueSets = [
        entitySpec.identity,
        ...spec.domain.constraints
          .filter((item) => item.entity === entityId && item.kind === "unique")
          .map((item) => item.fields),
      ];
      for (const fields of uniqueSets) {
        const seen = new Set();
        for (const record of activeByEntity[entityId]) {
          const identity = JSON.stringify(fields.map((field) => record[field]));
          if (seen.has(identity)) {
            throw new Error(
              `${entitySpec.title} backup duplicates ${fields.map(label).join(" and ")}.`,
            );
          }
          seen.add(identity);
        }
      }
    }
    const importedVersionIds = new Set(
      Object.values(next.records).flatMap((items) =>
        items.map((record) => record._record_uid),
      ),
    );
    if (
      Object.values(next.sample_overrides).some(
        (recordUid) => !importedVersionIds.has(recordUid),
      )
    ) {
      throw new Error("Backup contains a sample override without its replacement version.");
    }
  }

  function persist(next) {
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
      store = next;
      return true;
    } catch {
      announce(
        "The browser could not save this change. Export the current backup and free local storage before retrying.",
        true,
      );
      return false;
    }
  }

  function commit(entitySpec, action, form, current) {
    const operation = action?.operation || "create";
    const now = new Date().toISOString();
    const fields = entitySpec.fields.filter(
      (field) => !entitySpec.identity.includes(field.name),
    );
    const stableUid = current?.object_uid || uid();
    const before = current ? stripContext(current) : {};
    const record = Object.fromEntries(
      Object.entries(before).filter(([key]) => !key.startsWith("_")),
    );
    record.object_uid = stableUid;
    record.captured_at = current?.captured_at || now;
    record.updated_at = now;
    if (!current) {
      entitySpec.identity.forEach((name, index) => {
        const field = entitySpec.fields.find((item) => item.name === name);
        record[name] =
          index === 0
            ? `${entitySpec.id}-${stableUid.slice(0, 8)}`
            : ["integer", "number"].includes(field?.type)
              ? 1
              : `v${index + 1}`;
      });
    }
    for (const field of fields) {
      const value = parseField(field, form.get(field.name));
      if (value === undefined) delete record[field.name];
      else record[field.name] = value;
    }
    validateRecord(entitySpec, record, current);

    const next = clone(store);
    next.records[entitySpec.id] = next.records[entitySpec.id] || [];
    const recordUid = uid();
    record._record_uid = recordUid;
    record._version = Number(current?._version || 0) + 1;
    if (current) {
      record._supersedes = current.__record_key;
      if (current.__origin === "sample") {
        next.sample_overrides[current.__record_key] = recordUid;
      } else {
        const previous = next.records[entitySpec.id].find(
          (candidate) => recordKey(entitySpec.id, candidate) === current.__record_key,
        );
        if (!previous) {
          throw new Error("The selected record changed. Select it again and retry.");
        }
        previous._superseded_by = recordUid;
      }
    }
    next.records[entitySpec.id].push(record);
    next.receipts.push({
      receipt_id: uid(),
      object_uid: stableUid,
      record_uid: recordUid,
      entity: entitySpec.id,
      operation,
      captured_at: now,
      spec_id: spec.id,
      supersedes: current?.__record_key || null,
      changed_fields: fields
        .filter((field) => valueText(before[field.name]) !== valueText(record[field.name]))
        .map((field) => field.name),
      consequence: action?.consequence || entitySpec.description,
    });
    if (!persist(next)) return false;
    selected[entitySpec.id] = recordUid;
    return true;
  }

  function openCapture(entityId, action = null, current = null) {
    const entitySpec = entity(entityId);
    const operation = action?.operation || "create";
    const fields = entitySpec.fields.filter(
      (field) => !entitySpec.identity.includes(field.name),
    );
    const dialog = document.getElementById("capture-dialog");
    const versionNote =
      operation === "correct"
        ? '<p class="storage-note">Saving creates a correction version. The prior interpretation remains in history and export.</p>'
        : operation === "update"
          ? '<p class="storage-note">Saving creates a new version and preserves the prior state.</p>'
          : "";
    const submitLabel =
      operation === "correct"
        ? "Save correction"
        : operation === "update"
          ? "Save revision"
          : `Save ${entitySpec.title.toLowerCase()}`;
    document.getElementById("capture-content").innerHTML = `<div class="dialog-head"><div><h2 id="capture-title">${esc(
      action?.label || `Add ${entitySpec.title}`,
    )}</h2><p>${esc(
      action?.consequence || entitySpec.description,
    )}</p>${versionNote}</div><button class="icon-button" type="button" data-close aria-label="Close">Close</button></div><form id="capture-form"><div class="form-grid">${fields
      .map((field) => inputFor(field, entitySpec, current))
      .join(
        "",
      )}</div><p class="error" id="form-error" role="alert"></p><div class="dialog-actions"><button class="button" type="button" data-close>Cancel</button><button class="button primary" type="submit">${esc(
      submitLabel,
    )}</button></div></form>`;
    document
      .getElementById("capture-content")
      .querySelectorAll("[data-close]")
      .forEach((button) => button.addEventListener("click", () => dialog.close()));
    document.getElementById("capture-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const submit = event.currentTarget.querySelector('button[type="submit"]');
      submit.disabled = true;
      document.getElementById("form-error").textContent = "";
      try {
        if (!commit(entitySpec, action, new FormData(event.currentTarget), current)) {
          submit.disabled = false;
          return;
        }
        dialog.close();
        statusMessage =
          operation === "correct"
            ? `${entitySpec.title} corrected; the prior version remains in export history.`
            : operation === "update"
              ? `${entitySpec.title} revised; the prior version remains in export history.`
              : `${entitySpec.title} saved locally with an exportable receipt.`;
        errorMessage = "";
        render();
        focusAfterCapture(entitySpec);
      } catch (error) {
        document.getElementById("form-error").textContent =
          error instanceof Error ? error.message : "The record could not be saved.";
        submit.disabled = false;
      }
    });
    dialog.showModal();
    dialog.querySelector("input, select, textarea, button")?.focus();
  }

  const bullets = (items) =>
    `<ul>${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;

  function lookSection() {
    const world = spec.experience.visual_world;
    return `<div class="evidence-item"><strong>How this app looks</strong><p>${esc(
      world.name,
    )}. ${esc(world.mood)}.</p><p>${esc(world.color_strategy)}.</p><p>${esc(
      world.layout_principle,
    )}.</p><p>Type: ${esc(world.typography)}. Rendered as ${esc(
      plan.typography_label || "the app's default type",
    )}.</p><p>Room: ${esc(world.density)}. Rendered as ${esc(
      plan.density_label || "a working bench",
    )}.</p><p>Things that make it itself: ${esc(
      world.signature_elements.join(", "),
    )}.</p>${
      (plan.signature_labels || []).length
        ? `<p>Built into this app: ${esc((plan.signature_labels || []).join("; "))}.</p>`
        : ""
    }<p>Kept out on purpose: ${esc(world.avoid.join(", "))}.</p></div>`;
  }

  function remixSection() {
    const remix = spec.remix;
    const look = spec.look;
    const parts = [];
    if (remix.parent_spec) parts.push(`<p>Forked from ${esc(remix.parent_spec)}.</p>`);
    parts.push(`<p>Built from the ${esc(remix.selected_concept)} idea.</p>`);
    if (remix.fragments.length) {
      parts.push(
        `<p>Pieces kept from the other ideas:</p><ul>${remix.fragments
          .map(
            (item) =>
              `<li>${esc(item.fragment)}, from ${esc(item.from_concept)}. ${esc(item.reason)}</li>`,
          )
          .join("")}</ul>`,
      );
    }
    parts.push(`<p>What you decided:</p>${bullets(remix.user_decisions)}`);
    if (look) {
      parts.push(`<p>You approved the ${esc(look.look_id)} look.</p>`);
      if ((look.borrowed_fragments || []).length) {
        parts.push(
          `<p>Pieces you asked to bring over:</p><ul>${look.borrowed_fragments
            .map(
              (item) =>
                `<li>${esc(item.piece)}, from ${esc(item.from_concept)}.${
                  item.reason ? ` ${esc(item.reason)}` : ""
                }</li>`,
            )
            .join("")}</ul>`,
        );
      }
      if ((look.notes || []).length) {
        parts.push(`<p>What you wrote on the review page:</p>${bullets(look.notes)}`);
      }
    }
    return `<div class="evidence-item"><strong>What this app was put together from</strong>${parts.join(
      "",
    )}</div>`;
  }

  function flowSection() {
    const flows = spec.experience.flows.filter((flow) =>
      flow.steps.some((step) => step.view === activeViewId),
    );
    const shown = flows.length ? flows : spec.experience.flows;
    return `<div class="evidence-item"><strong>What you can do here</strong>${shown
      .map(
        (flow) =>
          `<p>${esc(flow.title)}. Starts when ${esc(flow.trigger)}. ${esc(
            flow.steps.map((step) => step.result).join(" Then "),
          )} You end with ${esc(flow.success)}</p>`,
      )
      .join("")}</div>`;
  }

  function accessSection() {
    const access = spec.experience.accessibility;
    return `<div class="evidence-item"><strong>How this app was checked</strong><p>It is built to meet ${esc(
      access.target,
    )}.</p><p>Patterns it follows:</p>${bullets(
      access.patterns,
    )}<p>What the keyboard does:</p>${bullets(
      access.keyboard_model,
    )}<p>Checks a person still has to do by hand:</p>${bullets(
      access.manual_checks,
    )}<p>On a small screen:</p>${bullets(spec.experience.responsive_strategy)}</div>`;
  }

  function openEvidence() {
    const dialog = document.getElementById("evidence-dialog");
    const current = view();
    let derivations = spec.derivations.filter(
      (item) =>
        item.output_path.includes(current.id) ||
        item.output_path === "domain.entities" ||
        item.output_path === "experience.visual_world",
    );
    if (!derivations.length) derivations = spec.derivations;
    const citationIds = new Set(derivations.flatMap((item) => item.evidence_ids));
    const citations = spec.evidence.filter((item) => citationIds.has(item.id));
    document.getElementById("evidence-content").innerHTML = `<div class="dialog-head"><div><h2 id="evidence-title">Why this app</h2><p>Material decisions trace to reviewed evidence or an explicit user choice.</p></div><button class="icon-button" type="button" data-close aria-label="Close">Close</button></div>${lookSection()}${remixSection()}${flowSection()}${accessSection()}${derivations
      .map(
        (item) =>
          `<div class="evidence-item"><strong>${esc(
            item.output_path,
          )}</strong><p>${esc(item.decision)}</p>${
            item.user_decision
              ? `<p><b>User decision:</b> ${esc(item.user_decision)}</p>`
              : ""
          }</div>`,
      )
      .join("")}${citations
      .map((item) => {
        const source = sources.get(item.source_id);
        const sourceLabel = source?.title || item.source_id;
        const heading = source?.url
          ? `<a href="${esc(
              source.url,
            )}" target="_blank" rel="noreferrer">${esc(sourceLabel)}</a>`
          : `<strong>${esc(sourceLabel)}</strong>`;
        return `<div class="evidence-item">${heading}<p>${esc(item.claim)}</p></div>`;
      })
      .join("")}`;
    dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
    dialog.showModal();
    dialog.querySelector("button")?.focus();
  }

  function exportData() {
    const activeRecords = Object.fromEntries(
      [...entityIds].map((entityId) => [
        entityId,
        records(entityId).map(stripContext),
      ]),
    );
    const payload = {
      backup_format: "foundry-owned-app",
      runtime_schema_version: RUNTIME_SCHEMA_VERSION,
      spec_id: spec.id,
      spec_version: spec.spec_version,
      exported_at: new Date().toISOString(),
      store,
      records: store.records,
      active_records: activeRecords,
      receipts: store.receipts,
      foundry_spec: spec,
      evidence: {
        sources: spec._source_records || [],
        citations: spec.evidence,
        derivations: spec.derivations,
      },
      derivations: spec.derivations,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${spec.id}-backup.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    announce("Complete data, history, receipts, spec, and evidence exported as JSON.");
  }

  async function restoreData(event) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    if (file.size > MAX_BACKUP_BYTES) {
      announce("Backup is larger than 10 MB and was not opened.", true);
      return;
    }
    try {
      const payload = JSON.parse(await file.text());
      if (payload.backup_format !== "foundry-owned-app") {
        throw new Error("This is not a Foundry owned-app backup.");
      }
      if (payload.spec_id !== spec.id || payload.spec_version !== spec.spec_version) {
        throw new Error(
          `Backup belongs to ${payload.spec_id || "another app"} spec ${
            payload.spec_version || "unknown"
          }; this app is ${spec.id} spec ${spec.spec_version}.`,
        );
      }
      if (Number(payload.runtime_schema_version) > RUNTIME_SCHEMA_VERSION) {
        throw new Error("Backup uses a newer runtime. Upgrade before restoring it.");
      }
      const restored = sanitizeStore(
        payload.store || { records: payload.records, receipts: payload.receipts },
        true,
      );
      validateBackup(restored);
      if (
        !globalThis.confirm(
          "Restore this backup? It will replace the current browser copy after validation.",
        )
      ) {
        announce("Restore cancelled; local data was not changed.");
        return;
      }
      if (!persist(restored)) return;
      statusMessage = "Backup restored after spec and schema validation.";
      errorMessage = "";
      render();
    } catch (error) {
      announce(
        error instanceof Error ? error.message : "Backup could not be restored.",
        true,
      );
    }
  }

  installKeyboard();
  render();
})();
