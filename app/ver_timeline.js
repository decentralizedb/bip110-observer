/*
 * La pagina del cronograma como la ve el visitante.
 *
 * Hermana de ver.js, y existe por el mismo motivo: revisar el diccionario no
 * es revisar la pagina. Ejecuta el JavaScript real de timeline.html sobre un
 * DOM minimo y escupe el texto que sale, con los datos de verdad.
 *
 * Uso:  node ver_timeline.js datos.json [es|en]
 *       (datos.json es lo que devuelve /api/timeline)
 */
"use strict";
const fs = require("fs");
const path = require("path");

const FUENTE = process.argv[2];
const LANG = process.argv.find(a => a === "en") ? "en" : "es";
const HTML = fs.readFileSync(path.join(__dirname, "static", "timeline.html"), "utf8");
const DATOS = FUENTE ? JSON.parse(fs.readFileSync(FUENTE, "utf8")) : null;

function nuevoElemento(id) {
  return {
    id, _html: "", _text: "", attrs: {}, dataset: {}, hidden: false,
    get innerHTML() { return this._html; }, set innerHTML(v) { this._html = String(v); },
    get textContent() { return this._text; }, set textContent(v) { this._text = String(v); },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
    addEventListener() {}, style: {},
  };
}

const DATA_K = [...new Set([...HTML.matchAll(/data-k="([A-Za-z0-9_]+)"/g)].map(m => m[1]))];
const els = {};
const conDataK = DATA_K.map(k => {
  const e = nuevoElemento("dk-" + k); e.dataset.k = k; return e;
});

global.document = {
  documentElement: { setAttribute() {}, lang: LANG },
  getElementById: id => els[id] || (els[id] = nuevoElemento(id)),
  querySelectorAll: sel => (sel === "[data-k]" ? conDataK : []),
  title: "",
};
global.window = { matchMedia: () => ({ matches: false, addEventListener() {} }) };
global.localStorage = { getItem: () => null, setItem() {} };
global.navigator = { language: LANG };
global.fetch = () => ({ then: () => ({ then: () => ({ catch() {} }) }) });

// Solo el <script> de la pagina, sin las etiquetas.
const js = HTML.slice(HTML.lastIndexOf("<script>") + 8, HTML.lastIndexOf("</script>"));
/* Las declaraciones del script son locales a la funcion que lo envuelve, asi
   que los datos se inyectan DENTRO, con un epilogo, y no desde fuera. Es lo
   que hace de verdad el fetch de la pagina: rellenar TL y volver a pintar. */
new Function("TLDATA", "LANGSET",
  js + "\n;LANG = LANGSET; if(TLDATA && TLDATA.ok) TL = TLDATA; paint();"
)(DATOS, LANG);

function limpia(h) {
  return String(h).replace(/<\/(tr|div)>/g, "\n").replace(/<\/t[dh]>/g, "  |  ")
                  .replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&quot;/g, '"')
                  .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&mdash;/g, "—")
                  .split("\n").map(s => s.trim()).filter(Boolean).join("\n");
}

const texto = k => (conDataK.find(e => e.dataset.k === k) || {}).textContent || "";

console.log("=".repeat(72));
console.log(document.title, " [", LANG, "]");
console.log("=".repeat(72));
for (const k of DATA_K) {
  const v = texto(k);
  if (!v) { console.log("  (VACIO) " + k); continue; }
  console.log("\n[" + k + "]\n" + v);
  if (k === "p2") console.log("\n" + limpia(els.docrows ? els.docrows.innerHTML : ""));
  if (k === "p3") console.log("\n" + limpia(els.blockrows ? els.blockrows.innerHTML : ""));
  if (k === "p5") console.log("\n" + limpia(els.extrows ? els.extrows.innerHTML : ""));
  if (k === "t6") {
    console.log("\n  " + (els.checkbig ? els.checkbig.textContent : "") +
                "\n  " + (els.checktxt ? els.checktxt.textContent : ""));
  }
}
