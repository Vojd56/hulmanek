"use strict";

const view = document.getElementById("view");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => `${Math.round(Math.max(0, x) * 100)} %`;

function storageGet(key) { try { return localStorage.getItem(key); } catch { return null; } }
function storageSet(key, value) { try { localStorage.setItem(key, value); } catch { /* soukromý režim */ } }

// PIN platí jen do zavření aplikace (sessionStorage), pak se zeptá znovu.
// Posílá se i jako cookie, aby se načetly fotky (<img> neposílá hlavičku x-pin).
function pinGet() { try { return sessionStorage.getItem("pin"); } catch { return null; } }
function pinSet(pin) {
  try { pin ? sessionStorage.setItem("pin", pin) : sessionStorage.removeItem("pin"); } catch { /* soukromý režim */ }
  const secure = location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `pin=${encodeURIComponent(pin || "")}; path=/; SameSite=Strict${secure}${pin ? "" : "; max-age=0"}`;
}
try { localStorage.removeItem("pin"); } catch { /* dřívější verze si PIN pamatovala natrvalo */ }
pinSet(pinGet());

function toast(msg, ms = 2600) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove("show"), ms);
}

// ---------- API ----------
// Server na Modalu po ~5 min bez provozu usne a probuzení trvá kolem 10 s. Když odpověď nepřichází
// a server dlouho neodpověděl, ukážeme, že se probouzí (u rozpoznání, které jen dlouho počítá, ne).
const AWAKE_MS = 4.5 * 60 * 1000;
const waking = { lastOk: 0, pending: 0, timer: null };
function trackRequest(promise) {
  const asleep = Date.now() - waking.lastOk > AWAKE_MS;
  waking.pending++;
  if (asleep && !waking.timer) {
    waking.timer = setTimeout(() => document.getElementById("waking").hidden = false, 1200);
  }
  const done = (ok) => {
    if (ok) waking.lastOk = Date.now();
    if (--waking.pending <= 0 || ok) {
      clearTimeout(waking.timer); waking.timer = null;
      document.getElementById("waking").hidden = true;
    }
  };
  promise.then(() => done(true), () => done(false));
  return promise;
}

function headers(extra = {}) {
  const pin = pinGet();
  return pin ? { ...extra, "x-pin": pin } : extra;
}

async function api(path, opts = {}) {
  const res = await trackRequest(fetch(path, { ...opts, headers: headers(opts.headers) }));
  if (res.status === 401) { await askPin(); return api(path, opts); }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Chyba ${res.status}`);
  return body;
}

const json = (method, data) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

/** Nahrání souborů s průběhem (fetch neumí průběh odesílání). */
function upload(path, form, onProgress) {
  return trackRequest(new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    for (const [k, v] of Object.entries(headers())) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.upload.onload = () => onProgress?.(1, true);
    xhr.onload = async () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* prázdná odpověď */ }
      if (xhr.status === 401) { await askPin(); return upload(path, form, onProgress).then(resolve, reject); }
      xhr.status < 300 ? resolve(body) : reject(new Error(body.detail || `Chyba ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("Server není dostupný. Je počítač zapnutý a jste na stejné síti?"));
    xhr.send(form);
  }));
}

function askPin() {
  return new Promise((resolve) => {
    view.innerHTML = `
      <div class="card stack">
        <h2>Zadejte PIN</h2>
        <p class="muted">Aplikace je chráněná PINem. Po zavření aplikace se na něj zeptá znovu.</p>
        <input type="password" id="pin" inputmode="numeric" autocomplete="current-password">
        <button class="btn primary big" id="pinOk">Pokračovat</button>
      </div>`;
    document.getElementById("pinOk").onclick = () => {
      pinSet(document.getElementById("pin").value.trim());
      resolve();
    };
  });
}

let individualsCache = null;
async function individuals(force = false) {
  if (!individualsCache || force) individualsCache = await api("/api/individuals");
  return individualsCache;
}

const ICONS = {
  camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3z"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
  check: '<path d="m5 12 5 5 9-10"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  back: '<path d="M15 6l-6 6 6 6"/>',
  upload: '<path d="M12 15V4M8 8l4-4 4 4"/><path d="M4 15v5h16v-5"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="1.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  portrait: '<circle cx="12" cy="9" r="4"/><path d="M5 20c1-4 4-6 7-6s6 2 7 6"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  paw: '<circle cx="6" cy="10" r="2.2"/><circle cx="9.5" cy="5.8" r="2.2"/><circle cx="14.5" cy="5.8" r="2.2"/><circle cx="18" cy="10" r="2.2"/><path d="M12 11c-2.6 0-6 4.2-6 7.1C6 19.9 7.4 21 9 21c1.2 0 2-.6 3-.6s1.8.6 3 .6c1.6 0 3-1.1 3-2.9 0-2.9-3.4-7.1-6-7.1z"/>',
};
const FILLED = new Set(["paw"]);
const icon = (name) => `<svg class="icon${FILLED.has(name) ? " fill" : ""}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;

/** České tvary podle počtu: plural(2, "rok", "roky", "let") → "2 roky". */
const plural = (n, one, few, many) => `${n} ${n === 1 ? one : n >= 2 && n <= 4 ? few : many}`;

const KIND_LABEL = { face: "obličej", body: "tělo" };

/** Spodní nabídka akcí; vrátí klíč zvolené akce. */
function sheet(imageUrl, actions) {
  return new Promise((resolve) => {
    const el = document.createElement("div");
    el.className = "sheet-backdrop";
    el.innerHTML = `<div class="sheet" role="dialog">
      ${imageUrl ? `<img src="${imageUrl}" alt="">` : ""}
      ${actions.map(([key, label, cls]) => `<button class="btn ${cls}" data-act="${key}">${esc(label)}</button>`).join("")}
    </div>`;
    const close = (key) => { el.remove(); resolve(key); };
    el.onclick = (e) => close(e.target.closest("[data-act]")?.dataset.act ?? "cancel");
    document.body.appendChild(el);
  });
}

// ---------- routing ----------
const routes = [
  [/^#?\/?$/, "identify", identifyView],
  [/^#\/hulmani$/, "hulmani", individualsView],
  [/^#\/hulman\/(\d+)$/, "hulmani", individualView],
  [/^#\/historie$/, "historie", historyView],
  [/^#\/stav$/, "stav", statusView],
];

async function router() {
  const hash = location.hash || "#/";
  for (const [re, tab, fn] of routes) {
    const m = hash.match(re);
    if (!m) continue;
    document.querySelectorAll(".tabbar a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
    view.innerHTML = '<div class="spinner"></div>';
    try { await fn(...m.slice(1)); } catch (e) { view.innerHTML = `<div class="card"><h3>Něco se nepovedlo</h3><p>${esc(e.message)}</p></div>`; }
    window.scrollTo(0, 0);
    return;
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", router);

// ---------- Rozpoznat ----------
let lastResult = null;

async function identifyView() {
  const list = await individuals(true);
  const emptyHint = list.length === 0
    ? `<div class="card"><h3>Galerie je zatím prázdná</h3><p>Nejdřív v záložce <a href="#/hulmani">Hulmani</a> přidejte jednotlivé hulmany a ke každému nahrajte fotky nebo videa.</p></div>`
    : "";
  view.innerHTML = `
    ${emptyHint}
    <div class="card stack">
      <h2>Kdo je to?</h2>
      <p class="muted">Vyfoťte nebo natočte hulmana. Video z více úhlů dává spolehlivější výsledek než jedna fotka.</p>
      <label class="btn primary big" for="cam">${icon("camera")} Vyfotit</label>
      <input class="hidden-input" id="cam" type="file" accept="image/*" capture="environment">
      <label class="btn big" for="camVideo">${icon("video")} Natočit video</label>
      <input class="hidden-input" id="camVideo" type="file" accept="video/*" capture="environment">
      <label class="btn big" for="pick">${icon("image")} Vybrat z galerie</label>
      <input class="hidden-input" id="pick" type="file" accept="image/*,video/*">
    </div>
    <div id="result">${lastResult ? "" : ""}</div>`;
  for (const id of ["cam", "camVideo", "pick"]) {
    document.getElementById(id).onchange = (e) => e.target.files[0] && runIdentify(e.target.files[0]);
  }
  if (lastResult) renderResult(lastResult);
}

async function runIdentify(file) {
  const box = document.getElementById("result");
  const isVideo = file.type.startsWith("video/");
  box.innerHTML = `<div class="card"><p id="phase">Nahrávám ${isVideo ? "video" : "fotku"}…</p><div class="progress"><i id="bar"></i></div></div>`;
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await upload("/api/identify", form, (p, done) => {
      document.getElementById("bar").style.width = `${p * 100}%`;
      if (done) document.getElementById("phase").textContent = isVideo ? "Prohlížím snímky videa…" : "Hledám hulmana a porovnávám…";
    });
    lastResult = res;
    renderResult(res);
  } catch (e) {
    box.innerHTML = `<div class="card"><h3>Rozpoznání selhalo</h3><p>${esc(e.message)}</p></div>`;
  }
}

function verdict(status, cands, video) {
  const top = cands[0];
  if (status === "empty") return ["empty", "Galerie je prázdná"];
  if (status === "unknown") return ["unknown", "Neznámý hulman"];
  if (status === "uncertain") return ["uncertain", `${top.name}, nebo ${cands[1].name}?`];
  const extra = video ? ` (vyhrál ${top.wins}× z ${top.frames} snímků)` : "";
  return ["match", `Je to ${top.name}${extra}`];
}

function candidatesHtml(cands) {
  return cands.map((c, i) => `
    <div class="cand ${i === 0 ? "first" : ""}">
      <span class="name">${esc(c.name)}</span>
      <span class="pct">shoda ${pct(c.score)}${c.face != null && c.body != null ? ` · obličej ${pct(c.face)} · tělo ${pct(c.body)}` : ""}</span>
      <div class="bar"><i style="width:${Math.max(2, c.score * 100)}%"></i></div>
    </div>`).join("");
}

function overlay(res) {
  const rects = res.animals.flatMap((a) => Object.entries(a.boxes)
    .filter(() => !a.fallback)
    .map(([kind, b]) => `<rect class="${kind}" x="${b[0]}" y="${b[1]}" width="${b[2] - b[0]}" height="${b[3] - b[1]}" rx="6"/>`)
    .concat(a.fallback || res.animals.length < 2 ? [] : [`<text x="${a.box[0] + 8}" y="${a.box[1] + 34}" font-size="${Math.max(24, res.width / 30)}">${a.index + 1}</text>`]));
  return `<div class="photo"><img src="${res.media_url}" alt="Analyzovaný snímek">
    <svg viewBox="0 0 ${res.width} ${res.height}" preserveAspectRatio="none">${rects.join("")}</svg></div>`;
}

function confirmControls(key, topCand, list) {
  const options = list.map((i) => `<option value="${i.id}">${esc(i.name)}</option>`).join("");
  return `
    <div class="stack" data-confirm="${key}">
      ${topCand ? `<button class="btn ok" data-yes="${topCand.individual_id}">${icon("check")} Ano, je to ${esc(topCand.name)}</button>` : ""}
      <select data-other>
        <option value="">${topCand ? "Ne, je to…" : "Je to…"}</option>
        ${options}
        <option value="__new">Nový hulman…</option>
      </select>
      <label class="check"><input type="checkbox" data-learn checked> Uložit do galerie (zlepší příští rozpoznání)</label>
    </div>`;
}

async function renderResult(res) {
  const list = await individuals();
  const box = document.getElementById("result");
  let html = `<div class="card stack">${overlay(res)}`;
  if (res.media_type === "video") {
    const [cls, text] = verdict(res.video.status, res.video.candidates, true);
    html += `<p class="muted small">Video: ${res.video.frames} snímků, zobrazen nejlepší snímek v ${res.best_frame_time} s.</p>
      <div class="verdict ${cls}">${esc(text)}</div>${candidatesHtml(res.video.candidates)}
      ${confirmControls("video", res.video.status === "match" || res.video.status === "uncertain" ? res.video.candidates[0] : null, list)}`;
  } else if (res.animals.length > 1) {
    html += `<p class="muted">Na fotce je ${res.animals.length} hulmanů, výsledky jsou níže podle čísel.</p>`;
  }
  html += "</div>";
  if (res.media_type === "image") {
    for (const a of res.animals) {
      const [cls, text] = verdict(a.status, a.candidates, false);
      const showTop = a.status === "match" || a.status === "uncertain";
      html += `<div class="card">
        ${res.animals.length > 1 ? `<h3>Hulman č. ${a.index + 1}</h3>` : ""}
        <div class="verdict ${cls}">${esc(text)}</div>
        ${a.fallback ? `<p class="muted small">Hulmana se na fotce nepodařilo ohraničit, porovnávám celý snímek.</p>` : ""}
        <div class="crops">${a.crops.map((c) => `
          <button class="crop" data-crop-kind="${c.kind}" title="Klepnutím přepnete obličej / tělo">
            <img src="${c.url}" alt=""><span class="k">${KIND_LABEL[c.kind]}</span></button>`).join("")}</div>
        <p class="muted small">Špatně určený druh výřezu? Klepněte na něj a před potvrzením přepněte obličej / tělo.</p>
        ${candidatesHtml(a.candidates)}
        ${confirmControls(String(a.index), showTop ? a.candidates[0] : null, list)}
      </div>`;
    }
  }
  box.innerHTML = html;
  box.querySelectorAll("[data-crop-kind]").forEach((b) => b.onclick = () => {
    b.dataset.cropKind = b.dataset.cropKind === "face" ? "body" : "face";
    b.querySelector(".k").textContent = KIND_LABEL[b.dataset.cropKind];
  });
  box.querySelectorAll("[data-confirm]").forEach((el) => {
    const idx = el.dataset.confirm === "video" ? null : Number(el.dataset.confirm);
    const learn = () => el.querySelector("[data-learn]").checked;
    el.querySelector("[data-yes]")?.addEventListener("click", () => confirmAs(res, idx, Number(el.querySelector("[data-yes]").dataset.yes), learn(), el));
    el.querySelector("[data-other]").addEventListener("change", async (e) => {
      let id = e.target.value;
      if (!id) return;
      if (id === "__new") {
        const name = prompt("Jméno nového hulmana:");
        if (!name) { e.target.value = ""; return; }
        try { id = (await api("/api/individuals", json("POST", { name }))).id; await individuals(true); }
        catch (err) { toast(err.message); e.target.value = ""; return; }
      }
      confirmAs(res, idx, Number(id), learn(), el);
    });
  });
}

async function confirmAs(res, animalIndex, individualId, learn, el) {
  const cropButtons = [...(el.closest(".card")?.querySelectorAll("[data-crop-kind]") ?? [])];
  const cropKinds = animalIndex === null || !cropButtons.length ? null : cropButtons.map((b) => b.dataset.cropKind);
  try {
    const r = await api(`/api/identifications/${res.id}/confirm`, json("POST", { individual_id: individualId, animal_index: animalIndex, learn, crop_kinds: cropKinds }));
    el.closest(".card")?.querySelectorAll("[data-crop-kind]").forEach((b) => (b.disabled = true));
    const name = (await individuals(true)).find((i) => i.id === individualId)?.name ?? "";
    el.innerHTML = `<p class="verdict match small">${icon("check")} Uloženo jako ${esc(name)}${learn ? ` · přidáno ${r.added} výřezů do galerie` : ""}</p>`;
  } catch (e) { toast(e.message); }
}

// ---------- Hulmani ----------
const MIN_SAMPLES = 20;

async function individualsView() {
  const list = await individuals(true);
  const year = new Date().getFullYear();
  const details = (i) => [
    i.sex === "M" ? "Samec" : i.sex === "F" ? "Samice" : "",
    i.birth_year && i.birth_year <= year ? `Věk: ${plural(year - i.birth_year, "rok", "roky", "let")}` : "",
  ].filter(Boolean).join(" • ");
  view.innerHTML = `
    <div class="page-head">
      <div>
        <h2>Výběh hulmanů <span class="muted">${list.length}</span></h2>
        <span class="sub">Správa jedinců a jejich referenčních fotek</span>
      </div>
      <button class="btn primary" id="add">${icon("plus")} Přidat</button>
    </div>
    <div id="addForm"></div>
    ${list.length ? "" : `<div class="card"><p>Zatím tu nikdo není. Přidejte prvního hulmana a nahrajte k němu fotky nebo krátká videa z různých stran.</p></div>`}
    <div class="roster">${list.map((i) => `
      <a class="roster-item" href="#/hulman/${i.id}">
        <div class="avatar" style="${i.cover_url ? `background-image:url('${i.cover_url}')` : ""}">${i.cover_url ? "" : icon("paw")}</div>
        <div class="info">
          <b>${esc(i.name)}</b>
          ${details(i) ? `<span class="muted">${details(i)}</span>` : ""}
          <span class="count ${i.samples >= MIN_SAMPLES ? "ready" : ""}" title="${i.face_samples || 0} obličejů · ${i.body_samples || 0} těl">${plural(i.samples, "vzorek", "vzorky", "vzorků")} v AI</span>
        </div>
        ${icon("chevron")}
      </a>`).join("")}</div>`;
  document.getElementById("add").onclick = () => {
    document.getElementById("addForm").innerHTML = individualForm({}, "Přidat hulmana");
    bindIndividualForm(null);
  };
}

function individualForm(i, title) {
  return `<div class="card">
    <h3>${title}</h3>
    <label for="f-name">Jméno</label><input type="text" id="f-name" value="${esc(i.name)}" autocomplete="off">
    <label for="f-sex">Pohlaví</label>
    <select id="f-sex"><option value="">—</option>
      <option value="M" ${i.sex === "M" ? "selected" : ""}>samec</option>
      <option value="F" ${i.sex === "F" ? "selected" : ""}>samice</option></select>
    <label for="f-year">Rok narození</label><input type="number" id="f-year" value="${esc(i.birth_year)}" inputmode="numeric">
    <label for="f-notes">Poznámky (znaky, jizvy…)</label><textarea id="f-notes" rows="2">${esc(i.notes)}</textarea>
    <div class="btn-row" style="margin-top:12px"><button class="btn primary" id="f-save">Uložit</button></div>
  </div>`;
}

function bindIndividualForm(id) {
  document.getElementById("f-save").onclick = async () => {
    const data = {
      name: document.getElementById("f-name").value,
      sex: document.getElementById("f-sex").value || null,
      birth_year: Number(document.getElementById("f-year").value) || null,
      notes: document.getElementById("f-notes").value || null,
    };
    try {
      if (id) { await api(`/api/individuals/${id}`, json("PUT", data)); router(); }
      else { const r = await api("/api/individuals", json("POST", data)); location.hash = `#/hulman/${r.id}`; }
      individualsCache = null;
    } catch (e) { toast(e.message); }
  };
}

async function individualView(id) {
  const i = await api(`/api/individuals/${id}`);
  const faces = i.samples.filter((s) => s.kind === "face").length;
  const bodies = i.samples.length - faces;
  view.innerHTML = `
    <p><a class="back" href="#/hulmani">${icon("back")} Hulmani</a></p>
    <h2>${esc(i.name)}</h2>
    <p class="muted">${[i.sex === "M" ? "samec" : i.sex === "F" ? "samice" : "", i.birth_year ? `nar. ${i.birth_year}` : "", i.notes].filter(Boolean).map(esc).join(" · ")}</p>
    <div class="card stack">
      <h3>Přidat fotky nebo videa</h3>
      <p class="muted small">Ideálně stovky záběrů: obličej zepředu, oba boky, záda, různé světlo. Z videa se bere jeden snímek za sekundu. Na záběru má být jen tento hulman (jinak se vezme největší).</p>
      <label class="btn primary" for="enroll">${icon("upload")} Vybrat soubory</label>
      <input class="hidden-input" id="enroll" type="file" accept="image/*,video/*" multiple>
      <label class="btn" for="enrollCam">${icon("camera")} Vyfotit teď</label>
      <input class="hidden-input" id="enrollCam" type="file" accept="image/*" capture="environment">
      <label class="btn" for="enrollVideo">${icon("video")} Natočit teď</label>
      <input class="hidden-input" id="enrollVideo" type="file" accept="video/*" capture="environment">
      <div id="enrollStatus"></div>
    </div>
    <div class="card">
      <h3>Galerie: ${faces} obličejů, ${bodies} těl</h3>
      ${i.samples.length < MIN_SAMPLES ? `<p class="badge warn">Pro spolehlivé rozpoznání přidejte aspoň ${MIN_SAMPLES} záběrů.</p>` : ""}
      <p class="muted small">Klepnutím na výřez ho můžete přepnout mezi obličejem a tělem, nebo smazat (např. když je na něm jiný hulman).</p>
      <div class="samples">${i.samples.map((s) => `
        <button data-sample="${s.id}"><img loading="lazy" src="${s.url}" alt=""><span class="k">${KIND_LABEL[s.kind]}${s.origin === "confirmed" ? " · potvrzeno" : ""}</span></button>`).join("")}</div>
    </div>
    <div id="editForm">${individualForm(i, "Upravit údaje")}</div>
    <button class="btn danger" id="del">Smazat hulmana i s fotkami</button>`;
  bindIndividualForm(id);
  for (const inputId of ["enroll", "enrollCam", "enrollVideo"]) {
    document.getElementById(inputId).onchange = (e) => enrollFiles(id, [...e.target.files]);
  }
  view.querySelectorAll("[data-sample]").forEach((b) => b.onclick = async () => {
    const sample = i.samples.find((x) => String(x.id) === b.dataset.sample);
    const other = sample.kind === "face" ? "body" : "face";
    const choice = await sheet(b.querySelector("img").src, [
      ["switch", `Přepnout na ${KIND_LABEL[other]}`, "primary"],
      ["delete", "Smazat výřez", "danger"],
      ["cancel", "Zrušit", ""],
    ]);
    try {
      if (choice === "switch") {
        await api(`/api/samples/${sample.id}`, json("PATCH", { kind: other }));
        sample.kind = other;
        individualsCache = null;
        individualView(id);
        toast(`Přepnuto na ${KIND_LABEL[other]}`);
      } else if (choice === "delete") {
        await api(`/api/samples/${sample.id}`, { method: "DELETE" });
        b.remove();
      }
    } catch (e) { toast(e.message); }
  });
  document.getElementById("del").onclick = async () => {
    if (!confirm(`Opravdu smazat ${i.name} včetně všech fotek?`)) return;
    await api(`/api/individuals/${id}`, { method: "DELETE" });
    individualsCache = null;
    location.hash = "#/hulmani";
  };
}

async function enrollFiles(id, files) {
  const status = document.getElementById("enrollStatus");
  let added = 0, noAnimal = 0, multiple = 0;
  for (const [n, f] of files.entries()) {
    status.innerHTML = `<p>${n + 1}/${files.length}: ${esc(f.name)}</p><div class="progress"><i id="ebar"></i></div><p class="muted small" id="ephase">Nahrávám…</p>`;
    const form = new FormData();
    form.append("files", f);
    try {
      const r = await upload(`/api/individuals/${id}/media`, form, (p, done) => {
        document.getElementById("ebar").style.width = `${p * 100}%`;
        if (done) document.getElementById("ephase").textContent = "Vyhledávám hulmana na snímcích…";
      });
      for (const rep of r.reports) {
        if (rep.error) toast(`${f.name}: ${rep.error}`);
        added += rep.added || 0; noAnimal += rep.no_animal || 0; multiple += rep.multiple || 0;
      }
    } catch (e) { toast(e.message); }
  }
  individualsCache = null;
  await individualView(id);
  const notes = [noAnimal && `na ${noAnimal} snímcích jsem hulmana nenašel`, multiple && `na ${multiple} snímcích bylo víc zvířat`].filter(Boolean);
  toast(`Přidáno ${added} výřezů${notes.length ? ` (${notes.join(", ")})` : ""}.`, 5000);
}

// ---------- Historie ----------
async function historyView() {
  const rows = await api("/api/identifications?limit=50");
  view.innerHTML = `<h2>Historie</h2><div class="card">${rows.length ? rows.map((r) => `
    <div class="list-item">
      <img src="${r.media_url}" alt="">
      <div>
        <b>${esc(r.confirmed_name || r.top?.name || "Neznámý")}</b>
        ${r.confirmed_name ? `<span class="badge ok">potvrzeno</span>` : r.top ? `<span class="badge">${pct(r.top.score)}</span>` : ""}
        <div class="muted small">${r.media_type === "video" ? "video · " : ""}${new Date(r.created_at).toLocaleString("cs-CZ")}</div>
      </div>
    </div>`).join("") : `<p class="muted">Zatím žádná rozpoznání.</p>`}</div>`;
}

// ---------- Stav ----------
async function statusView() {
  const s = await api("/api/status", { headers: {} });
  if (s.pin_required && !s.pin_ok) { await askPin(); return statusView(); }
  view.innerHTML = `
    <div class="page-head">
      <h2>Stav a přesnost</h2>
      ${s.pin_required ? `<button class="btn" id="lock">${icon("lock")} Zamknout</button>` : ""}
    </div>
    <div class="card">
      <dl class="kv">
        <dt>Počítá</dt><dd>${esc(s.device)}</dd>
        <dt>Model otisků</dt><dd>MegaDescriptor ${esc(s.embedder)} ${s.finetuned ? '<span class="badge ok">doladěný</span>' : '<span class="badge">obecný</span>'}</dd>
        <dt>Detektor</dt><dd>${s.detector ? `YOLO-World (${esc(s.detector_weights)})` : `<span class="badge warn">nedostupný</span> ${esc(s.detector_error || "")}`}</dd>
        <dt>Hulmanů</dt><dd>${s.individuals}</dd>
        <dt>Výřezů v galerii</dt><dd>${s.gallery_size}</dd>
      </dl>
      ${s.rebuild.running ? `<p>Přepočítávám galerii: ${s.rebuild.done}/${s.rebuild.total}</p>` : ""}
    </div>
    <div class="card">
      <h3>Práh pro „neznámý hulman“</h3>
      <p class="muted small">Když je nejlepší shoda pod prahem, aplikace řekne, že hulmana nezná.</p>
      <input type="range" id="thr" min="0" max="1" step="0.01" value="${s.threshold}" style="width:100%">
      <p>Práh: <b id="thrVal">${pct(s.threshold)}</b></p>
    </div>
    <div class="card">
      <h3>Obličej, nebo tělo?</h3>
      <p class="muted small">Když jsou na snímku vidět oba, kolik má rozhodovat obličej. Výřezy obličejů se porovnávají jen s obličeji a těla jen s těly.</p>
      <input type="range" id="fw" min="0" max="1" step="0.05" value="${s.face_weight}" style="width:100%">
      <p>Obličej <b id="fwVal">${pct(s.face_weight)}</b> · tělo <b id="bwVal">${pct(1 - s.face_weight)}</b></p>
    </div>
    <div class="card stack">
      <h3>Jak přesně to poznává?</h3>
      <p class="muted small">Každý výřez se zkusí rozpoznat podle ostatních fotek z jiných souborů. Hulmani s fotkami z jediného souboru se přeskočí.</p>
      <button class="btn primary" id="eval">Vyhodnotit přesnost</button>
      <div id="evalOut"></div>
    </div>
    <div class="card stack">
      <h3>Doladěný model</h3>
      <p class="muted small">Po spuštění <code>scripts/finetune.py</code> na počítači načtěte nový model tady (galerie se přepočítá).</p>
      <button class="btn" id="reload">Načíst doladěný model</button>
    </div>
    <div class="card">
      <h3>Tipy pro dobré výsledky</h3>
      <ul class="tips small">
        <li>Ke každému hulmanovi nahrajte videa z různých stran, dnů a světla.</li>
        <li>Pro rozpoznání je lepší krátké video (3–5 s) než jedna fotka.</li>
        <li>Potvrzujte výsledky tlačítkem „Ano, je to…“, galerie se tím sama zlepšuje.</li>
        <li>Až bude mít každý hulman aspoň ~100 záběrů, spusťte doladění modelu.</li>
      </ul>
    </div>`;
  document.getElementById("lock")?.addEventListener("click", () => { pinSet(""); individualsCache = null; location.hash = "#/"; });
  const thr = document.getElementById("thr");
  thr.oninput = () => (document.getElementById("thrVal").textContent = pct(thr.value));
  thr.onchange = async () => { await api("/api/settings", json("POST", { threshold: Number(thr.value) })); toast("Práh uložen"); };
  const fw = document.getElementById("fw");
  fw.oninput = () => {
    document.getElementById("fwVal").textContent = pct(fw.value);
    document.getElementById("bwVal").textContent = pct(1 - fw.value);
  };
  fw.onchange = async () => { await api("/api/settings", json("POST", { face_weight: Number(fw.value) })); toast("Váha uložena"); };
  document.getElementById("eval").onclick = async (e) => {
    e.target.disabled = true;
    const out = document.getElementById("evalOut");
    out.innerHTML = '<div class="spinner"></div>';
    try {
      const r = await api("/api/evaluate", { method: "POST" });
      if (!r.samples) { out.innerHTML = `<p class="muted">Zatím není co vyhodnotit. Každý hulman potřebuje fotky aspoň ze 2 různých souborů.</p>`; return; }
      out.innerHTML = `
        <p><b>Správně na 1. místě: ${pct(r.top1)}</b> · v top 3: ${pct(r.top3)} · ${r.samples} výřezů</p>
        ${r.suggested_threshold != null ? `<p>Doporučený práh: ${pct(r.suggested_threshold)} <button class="btn" id="useThr">Použít</button></p>` : ""}
        ${r.skipped_individuals.length ? `<p class="muted small">Přeskočeno (fotky jen z 1 souboru): ${r.skipped_individuals.map(esc).join(", ")}</p>` : ""}
        <table><tr><th>Hulman</th><th class="num">výřezů</th><th class="num">správně</th></tr>
        ${r.per_individual.map((p) => `<tr><td>${esc(p.name)}</td><td class="num">${p.samples}</td><td class="num">${pct(p.top1)}</td></tr>`).join("")}</table>`;
      document.getElementById("useThr")?.addEventListener("click", async () => {
        await api("/api/settings", json("POST", { threshold: r.suggested_threshold }));
        thr.value = r.suggested_threshold; thr.oninput(); toast("Práh nastaven");
      });
    } catch (err) { out.innerHTML = `<p>${esc(err.message)}</p>`; }
    finally { e.target.disabled = false; }
  };
  document.getElementById("reload").onclick = async (e) => {
    e.target.disabled = true;
    try { const r = await api("/api/reload-model", { method: "POST" }); toast(`Načteno: ${r.model}`); statusView(); }
    catch (err) { toast(err.message); e.target.disabled = false; }
  };
}

// přepínač světlý/tmavý režim v záhlaví; bez uložené volby platí nastavení systému
const darkQuery = matchMedia("(prefers-color-scheme: dark)");
const isDark = () => (document.documentElement.dataset.theme || (darkQuery.matches ? "dark" : "light")) === "dark";
function syncTheme() {
  document.querySelector('meta[name="theme-color"]').content = isDark() ? "#17130e" : "#fff8f4";
  const btn = document.getElementById("theme-toggle");
  btn.setAttribute("aria-label", isDark() ? "Přepnout na světlý režim" : "Přepnout na tmavý režim");
}
document.getElementById("theme-toggle").addEventListener("click", () => {
  const next = isDark() ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch (e) {}
  syncTheme();
});
darkQuery.addEventListener("change", syncTheme);
syncTheme();

if ("serviceWorker" in navigator && location.protocol === "https:") {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
router();
