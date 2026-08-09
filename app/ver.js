/*
 * La pagina como la ve el visitante, AHORA, con los datos de produccion.
 *
 * stress.js prueba escenarios inventados. Esto hace lo contrario: coge las
 * respuestas reales de la API y ejecuta el mismo JavaScript de index.html
 * sobre un DOM minimo, para poder leer el texto que sale de verdad.
 *
 * Existe porque revisar el diccionario no es revisar la pagina. Un texto
 * puede estar impecable y estar contando la cifra de la cadena equivocada,
 * y eso solo se ve con el resultado delante. Paso justo eso la noche de la
 * separacion: cinco repasos del diccionario y el error seguia en pantalla.
 *
 * Uso:  node ver.js [https://otro.dominio] [es|en]
 */
"use strict";
const fs = require("fs");
const path = require("path");
const https = require("https");

const BASE = process.argv[2] && process.argv[2].startsWith("http")
           ? process.argv[2] : "https://bip110.dinerosinreglas.com";
const LANG = process.argv.find(a => a === "en") ? "en" : "es";
const HTML = fs.readFileSync(path.join(__dirname, "static", "index.html"), "utf8");

function pide(ruta) {
  return new Promise(res => {
    https.get(BASE + ruta, {headers: {"User-Agent": "ver.js"}}, r => {
      let b = "";
      r.on("data", c => b += c);
      r.on("end", () => { try { res(JSON.parse(b)); } catch (e) { res(null); } });
    }).on("error", () => res(null));
  });
}

/* ------------------------------------------------------------ DOM minimo */
function nuevoElemento(id) {
  const clases = new Set();
  return {
    id, _html: "", _text: "", attrs: {}, dataset: {},
    classList: { add: c => clases.add(c), remove: c => clases.delete(c),
                 contains: c => clases.has(c),
                 toggle: (c, on) => (on ? clases.add(c) : clases.delete(c)) },
    get innerHTML() { return this._html; }, set innerHTML(v) { this._html = String(v); },
    get textContent() { return this._text; }, set textContent(v) { this._text = String(v); },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
    removeAttribute(k) { delete this.attrs[k]; },
    hasAttribute(k) { return k in this.attrs; },
    addEventListener() {},
    querySelector() { return this._hijo || (this._hijo = nuevoElemento(id + "-h")); },
    style: {}, value: "20",
  };
}

const DATA_K = [...new Set([...HTML.matchAll(/data-k="([A-Za-z0-9_]+)"/g)].map(m => m[1]))];

function nuevoDom() {
  const els = {};
  const conDataK = DATA_K.map(k => { const e = nuevoElemento("dk-" + k); e.dataset.k = k; return e; });
  return {
    els, conDataK,
    documentElement: { lang: "es", attrs: {},
      setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; } },
    getElementById(id) { return els[id] || (els[id] = nuevoElemento(id)); },
    querySelectorAll(sel) { return sel === "[data-k]" ? conDataK : []; },
    addEventListener() {}, title: "",
  };
}

function cargarPanel(dom) {
  const ini = HTML.indexOf("/* ===================== i18n");
  const fin = HTML.lastIndexOf("</script>");
  let js = HTML.slice(ini, fin)
    .replace(/^load\(.*$/gm, "").replace(/^autoRefresh\(\);$/gm, "")
    .replace(/^renderAll\(\);$/gm, "");
  const win = { addEventListener() {}, removeEventListener() {}, scrollY: 0,
                isSecureContext: true,
                getSelection: () => ({removeAllRanges(){}, addRange(){}}),
                matchMedia: () => ({matches: false, addEventListener(){}, addListener(){}}) };
  const sandbox = { window: win, document: dom, navigator: {language: "es"}, console,
    localStorage: {getItem: () => null, setItem: () => {}},
    setInterval: () => 0, setTimeout: () => 0,
    fetch: () => Promise.resolve({json: () => Promise.resolve({})}),
    Intl, Math, Number, Object, Array, JSON, String, isNaN, parseFloat, parseInt, Set, Date };
  return new Function("sandbox", `with(sandbox){ ${js}
    return {setLang, setView, renderAll, DATA, t}; }`)(sandbox);
}

/* El HTML a texto plano, que es lo que lee una persona. */
const texto = h => String(h || "")
  .replace(/<[^>]+>/g, "\n")
  .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"')
  .split("\n").map(x => x.trim()).filter(Boolean).join("\n");

(async () => {
  const [miners, chain, pools, nodes, history, params] = await Promise.all(
    ["/api/miners", "/api/chain", "/api/pools", "/api/nodes", "/api/history", "/api/params"]
      .map(pide));

  const dom = nuevoDom();
  const panel = cargarPanel(dom);
  Object.assign(panel.DATA, {miners, chain, pools, nodes, history, params});
  panel.setLang(LANG);
  panel.setView(chain && chain.state ? chain.state : "pre_split");
  panel.renderAll();

  console.log("=".repeat(70));
  console.log("LA PAGINA AHORA MISMO ·", BASE, "·", LANG);
  console.log("estado:", chain && chain.state, "· core", chain && chain.nodes &&
              chain.nodes.core && chain.nodes.core.tip,
              "· knots", chain && chain.nodes && chain.nodes.knots && chain.nodes.knots.tip);
  console.log("=".repeat(70));

  const secciones = [
    ["CABECERA", ["fresh-txt"]],
    ["HEROE", ["dk-answerQ", "dk-answerA", "dk-answerLead", "herostat",
               "dk-riskKicker", "dk-riskShort", "herocd", "dk-boundary"]],
    ["LA CADENA", ["dk-chainTitle", "dk-chainMethod", "chain"]],
    ["LAS TRES FECHAS", ["dk-tlTitle", "tl"]],
    ["EL RECORRIDO", ["dk-strTitle", "strlead", "strrails", "strrows"]],
    ["MINEROS", ["dk-minersTitle", "miners"]],
    ["SIMULADOR", ["dk-simTitle", "simout", "simviable"]],
    ["POOLS", ["dk-poolsTitle", "pools", "coalition"]],
    ["NODOS", ["dk-nodesTitle", "nodes"]],
  ];
  for (const [nombre, ids] of secciones) {
    console.log("\n" + "-".repeat(70) + "\n" + nombre + "\n" + "-".repeat(70));
    for (const id of ids) {
      const e = dom.els[id];
      if (!e) continue;
      const t = [texto(e._html), e._text].filter(Boolean).join("\n").trim();
      if (t) console.log(t);
    }
  }
})();
