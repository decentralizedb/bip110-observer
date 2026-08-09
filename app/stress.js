/*
 * Banco de pruebas de la interfaz.
 *
 * Ejecuta DE VERDAD el JavaScript de index.html con datos sinteticos y
 * revisa el HTML que produce. Mirar la pagina a ojo solo encuentra lo que
 * pasa hoy; aqui se modelan situaciones que todavia no han ocurrido y que
 * el dia que ocurran no habra tiempo de arreglar.
 *
 * Que se comprueba en cada escenario, en los dos idiomas:
 *   - ningun marcador {x} sin rellenar
 *   - ni undefined, NaN, null, Infinity ni [object Object]
 *   - ninguna cifra clave sale como raya cuando el dato existe
 *   - los textos concuerdan con los datos (no afirmar "solo un pool"
 *     cuando hay cinco, ni "puede llegar" cuando ya no puede)
 *   - nada se sale de sitio: sin listas vacias donde deberia haber filas
 *
 * Uso:  node stress.js
 */
"use strict";
const fs = require("fs");
const path = require("path");

const HTML = fs.readFileSync(path.join(__dirname, "static", "index.html"), "utf8");

/* ---------------------------------------------------------------- DOM minimo */
function nuevoElemento(id) {
  const clases = new Set();
  return {
    id, _html: "", _text: "", attrs: {}, dataset: {},
    classList: {
      add: c => clases.add(c),
      remove: c => clases.delete(c),
      contains: c => clases.has(c),
      toggle: (c, on) => (on === undefined ? (clases.has(c) ? clases.delete(c) : clases.add(c))
                                           : (on ? clases.add(c) : clases.delete(c))),
    },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
    removeAttribute(k) { delete this.attrs[k]; },
    hasAttribute(k) { return k in this.attrs; },
    addEventListener() {},
    // El codigo busca hijos dentro de una parada; sin esto la rama no se
    // ejercita y un fallo ahi pasaria desapercibido.
    querySelector() { return this._hijo || (this._hijo = nuevoElemento(id + "-hijo")); },
    style: {},
    value: "20",
  };
}

// Claves que la pagina pinta con data-k. Se sacan del propio HTML para no
// mantener dos listas que se desincronicen.
const DATA_K = [...new Set([...HTML.matchAll(/data-k="([A-Za-z0-9_]+)"/g)].map(m => m[1]))];

function nuevoDom() {
  const els = {};
  const conDataK = DATA_K.map(k => { const e = nuevoElemento("dk-" + k); e.dataset.k = k; return e; });
  return {
    els, conDataK,
    documentElement: { lang: "en", attrs: {},
      setAttribute(k, v) { this.attrs[k] = v; },
      getAttribute(k) { return this.attrs[k]; } },
    getElementById(id) { return els[id] || (els[id] = nuevoElemento(id)); },
    querySelectorAll(sel) { return sel === "[data-k]" ? conDataK : []; },
    addEventListener() {},
    title: "",
  };
}

/* ------------------------------------------------------- carga del script */
function cargarPanel(dom) {
  const ini = HTML.indexOf("/* ===================== i18n");
  const fin = HTML.lastIndexOf("</script>");
  let js = HTML.slice(ini, fin);
  // El arranque hace fetch y temporizadores; aqui se inyectan los datos.
  js = js.replace(/^load\(.*$/gm, "").replace(/^autoRefresh\(\);$/gm, "")
         .replace(/^renderAll\(\);$/gm, "");
  // El navegador da mas cosas que document. Sin window, cualquier linea
  // del arranque que lo use revienta el escenario entero y el fallo real
  // queda escondido detras de "window is not defined".
  const win = {
    addEventListener() {}, removeEventListener() {},
    scrollY: 0, isSecureContext: true,
    getSelection: () => ({ removeAllRanges() {}, addRange() {} }),
    matchMedia: () => ({ matches: false, addEventListener() {} , addListener() {} }),
  };
  const sandbox = {
    window: win, document: dom, navigator: { language: "en" }, console,
    localStorage: { getItem: () => null, setItem: () => {} },
    setInterval: () => 0, fetch: () => Promise.resolve({ json: () => Promise.resolve({}) }),
    Intl, Math, Number, Object, Array, JSON, String, isNaN, parseFloat, parseInt, Set, Date,
    setTimeout: () => 0,
  };
  const fn = new Function("sandbox", `with(sandbox){ ${js}
    return {setLang, setView, renderAll, DATA, t};
  }`);
  return fn(sandbox);
}

/* ------------------------------------------------------------- escenarios */
const HASH_A = "00000000000000000000ad9b131e461cb0b0ae321081f36d7c88cccf285a5026";
const HASH_B = "0000000000000000000199aa4d0c1b2e3f4a5b6c7d8e9f0a1b2c3d4e5f607182";

const params = {
  bip: { name: "reduced_data", bit: 4, period: 2016, threshold_num: 1109,
         mandatory_start: 961632, mandatory_end: 963647, forced_lockin: 963648,
         activation_height: 965664, starttime: 1764547200 },
  target_spacing: 600, threshold_pct: 55.01, blocks_per_day: 144, history_periods: 5,
};

function miners(o = {}) {
  const scanned = o.scanned !== undefined ? o.scanned : 500;
  const sig = o.sig !== undefined ? o.sig : 13;
  const remaining = 2016 - scanned;
  return Object.assign({
    ok: true, node: "core", via: "clearnet", chain: "main",
    node_subversion: "/Satoshi:31.0.0/",
    tip: 959616 + scanned - 1,
    period: { index: 476, start: 959616, end: 961631, scanned, remaining },
    signalling_blocks: sig, threshold_blocks: 1109, threshold_pct: 55.01,
    pct_of_scanned: scanned ? +(sig / scanned * 100).toFixed(4) : 0,
    pct_of_period: +(sig / 2016 * 100).toFixed(4),
    threshold_reachable: (sig + remaining) >= 1109,
    max_possible: sig + remaining,
    signalling_by_pool: o.byPool !== undefined ? o.byPool : { Ocean: sig },
    milestones: {
      mandatory_signalling_start: { height: 961632, blocks_away: 1733, approx_days: 12.0, passed: false },
      forced_lockin: { height: 963648, blocks_away: 3749, approx_days: 26.0, passed: false },
      rules_active: { height: 965664, blocks_away: 5765, approx_days: 40.0, passed: false },
      in_mandatory_window: false,
    },
    minority_chain: { share: 0.026, share_pct: 2.6, interval_hours: 6.4, viable: false },
    milestone_projection: proyeccion(o.proy !== undefined ? o.proy
                                     : (scanned ? sig / scanned : 0)),
  }, o.extra || {});
}

/* Misma FORMA que devuelve signaling.milestone_projection(). No replica el
   calculo a proposito: si lo replicara, comprobaria dos veces el mismo
   error. Lo que se prueba aqui es que la interfaz aguante cada forma. */
function proyeccion(share) {
  const hitos = [["forced_lockin", 963648, 14], ["rules_active", 965664, 28],
                 ["rules_expire", 1018080, 392]];
  const lentos = { 0: [null, null, null], 0.0248: [565.4, 706.6, 1091.2],
                   1: [14, 28, 392] };
  const clave = share <= 0 ? 0 : (share >= 1 ? 1 : 0.0248);
  return {
    share, share_pct: +(share * 100).toFixed(2), fork_height: 961632,
    period: 2016, max_retarget_drop: 4,
    milestones: hitos.map((h, i) => {
      const lento = lentos[clave][i];
      return { key: h[0], height: h[1], blocks_after_fork: h[1] - 961632,
               nominal_days: h[2], nominal_years: +(h[2] / 365.25).toFixed(2),
               minority_days: lento,
               minority_years: lento === null ? null : +(lento / 365.25).toFixed(2),
               slowdown: lento === null ? null : +(lento / h[2]).toFixed(1),
               reachable: lento !== null };
    }),
  };
}

function history(pcts, byPool) {
  const per = pcts.map((p, i) => ({
    period: 471 + i, start: (471 + i) * 2016, end: (471 + i) * 2016 + 2015,
    blocks: 2016, signalling: Math.round(p * 2016 / 100), pct: p,
    by_pool: { Ocean: Math.round(p * 2016 / 100) },
  }));
  const agg = byPool || { Ocean: per.reduce((a, x) => a + x.signalling, 0) };
  const top = Object.entries(agg).sort((a, b) => b[1] - a[1])[0] || [null, 0];
  return {
    ok: true, periods: per, total_blocks: per.length * 2016,
    signalling_blocks: per.reduce((a, x) => a + x.signalling, 0),
    signalling_pct: 0.77, by_pool: agg,
    top_pool: top[0], top_pool_blocks: top[1],
    other_pools: Math.max(0, Object.keys(agg).length - 1),
  };
}

function pools(firmantes = ["Ocean"]) {
  const base = [["Foundry USA", 129], ["AntPool", 94], ["F2Pool", 79], ["ViaBTC", 41],
                ["SpiderPool", 38], ["Ocean", 19], ["MARA Pool", 21], ["Luxor", 18],
                ["SecPool", 24], ["Binance Pool", 11], ["Desconocido", 1], ["Trustpool", 7],
                ["BTC.com", 8], ["Braiins Pool", 4], ["SBI Crypto", 3], ["Poolin", 2],
                ["WhitePool", 1]];
  const total = base.reduce((a, x) => a + x[1], 0);
  return {
    ok: true, node: "core", via: "clearnet", sample_blocks: total,
    from_height: 959400, to_height: 959400 + total - 1,
    pools_identified: base.length - 1, unattributed_blocks: 1,
    unattributed_pct: +(1 / total * 100).toFixed(2),
    pools: base.map(([pool, blocks]) => ({
      pool, blocks, share_pct: +(blocks / total * 100).toFixed(2),
      signalling_blocks: firmantes.includes(pool) ? Math.max(1, Math.floor(blocks / 3)) : 0,
      signals: firmantes.includes(pool),
      signals_always: false,
    })),
  };
}

function chain(o = {}) {
  const st = o.state || "pre_split";
  return Object.assign({
    ok: true, state: st, degraded: false, single_node: false,
    split_height: st === "pre_split" ? null : 961632,
    // Las huellas del primer bloque divergente. Sin esto en el escenario, la
    // comprobacion que exige enseñarlas no se dispara nunca y da via libre a
    // un panel que afirma una separacion sin la prueba delante.
    split_hashes: st === "pre_split" ? null : { core: HASH_A, knots: HASH_B },
    reunified_height: st === "reunified" ? 962500 : null,
    nodes: {
      core: { ok: true, subversion: "/Satoshi:31.0.0/", tip: 961700, hash: HASH_A,
              chainwork: "0f", via: "clearnet", enforces: false },
      knots: { ok: true, subversion: "/Satoshi:29.3.0/Knots:20260508/",
               tip: st === "split" ? 961650 : 961700, hash: st === "split" ? HASH_B : HASH_A,
               chainwork: "0a", via: "tor", enforces: true },
    },
    majority: { node: "core", tip: 961700, hash: HASH_A, enforces: false, avg_interval_sec: 612,
                interval_blocks: 144, seconds_since_last_block: 300,
                blocks_since_split: st === "split" ? 68 : null },
    minority: { node: "knots", tip: 961650, hash: HASH_B, enforces: true, avg_interval_sec: 21600,
                interval_blocks: 18, seconds_since_last_block: 26000,
                blocks_since_split: st === "split" ? 18 : null },
    same_chain: st !== "split",
  }, o.extra || {});
}

function nodes(o = {}) {
  const total = o.total !== undefined ? o.total : 40;
  return Object.assign({
    ok: true, total_reachable_sampled: total,
    by_client: { Core: Math.round(total * 0.8), Knots: total - Math.round(total * 0.8) },
    pct: { Core: 80, Knots: 20 },
    by_network: { ipv4: total - 3, onion: 3 },
    by_rules: { undeclared: total - 4, declares: 3, knots_undeclared: 1 },
    pct_rules: { undeclared: 90, declares: 7.5, knots_undeclared: 2.5 },
    networks_probed: ["ipv4", "ipv6", "onion"], networks_skipped: ["cjdns", "i2p"],
    seeds_used: 11, seeds_por_nodo: { core: { aportadas: 3, total: 3 } },
  }, o.extra || {});
}

const ESCENARIOS = {
  "hoy, un pool y poca señalizacion":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(), chain: chain(), nodes: nodes() },

  "periodo recien empezado, un solo bloque escaneado":
    { params, miners: miners({ scanned: 1, sig: 0, byPool: {} }),
      history: history([0.35, 0.79, 0.45, 0.99, 1.29]), pools: pools([]),
      chain: chain(), nodes: nodes() },

  "nadie señaliza en todo el periodo":
    { params, miners: miners({ scanned: 2016, sig: 0, byPool: {} }),
      history: history([0, 0, 0, 0, 0]), pools: pools([]), chain: chain(), nodes: nodes() },

  "umbral ya inalcanzable":
    { params, miners: miners({ scanned: 1990, sig: 12 }),
      history: history([0.35, 0.79, 0.45, 0.99, 1.29]), pools: pools(), chain: chain(), nodes: nodes() },

  "señalizacion por encima del umbral":
    { params, miners: miners({ scanned: 1500, sig: 950,
        byPool: { "Foundry USA": 400, AntPool: 300, F2Pool: 150, ViaBTC: 60, Ocean: 40 } }),
      history: history([12, 25, 38, 49, 57]),
      pools: pools(["Foundry USA", "AntPool", "F2Pool", "ViaBTC", "Ocean", "SpiderPool"]),
      chain: chain(), nodes: nodes() },

  "tendencia bajando":
    { params, miners: miners({ sig: 4 }), history: history([4.2, 3.1, 2.0, 1.1, 0.4]),
      pools: pools(), chain: chain(), nodes: nodes() },

  "muchisimos pools señalizando":
    { params, miners: miners({ scanned: 900, sig: 300, byPool: {
        "Foundry USA": 80, AntPool: 60, F2Pool: 45, ViaBTC: 30, SpiderPool: 25,
        "MARA Pool": 20, Luxor: 15, SecPool: 10, Ocean: 8, "Binance Pool": 4,
        Trustpool: 2, "BTC.com": 1 } }),
      history: history([2, 5, 9, 14, 21]), pools: pools(["Foundry USA", "AntPool", "F2Pool"]),
      chain: chain(), nodes: nodes() },

  "cadenas separadas":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(), chain: chain({ state: "split" }), nodes: nodes() },

  // La rama minoritaria acaba de nacer: un solo bloque propio, asi que la
  // media sale de un unico intervalo y hay que decirlo en pantalla.
  "rama minoritaria recien nacida":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(), nodes: nodes(),
      chain: chain({ state: "split", extra: { minority: {
        node: "knots", tip: 961633, hash: HASH_B, enforces: true,
        avg_interval_sec: 25200, interval_blocks: 1,
        seconds_since_last_block: 25200, blocks_since_split: 1 } } }) },

  // La rama existe pero lleva semanas sin producir. El intervalo medio
  // conserva el valor que tenia, asi que lo unico que delata la parada es
  // cuanto hace del ultimo bloque.
  "rama minoritaria parada":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(), nodes: nodes(),
      chain: chain({ state: "split", extra: { minority: {
        node: "knots", tip: 961650, hash: HASH_B, enforces: true,
        avg_interval_sec: 21600, interval_blocks: 18,
        seconds_since_last_block: 2419200, blocks_since_split: 18 } } }) },

  // Separadas, pero la rama no ha producido ni un bloque todavia: no hay
  // ritmo que medir y el panel no puede inventarse uno.
  "rama minoritaria sin bloques propios":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(), nodes: nodes(),
      chain: chain({ state: "split", extra: { minority: {
        node: "knots", tip: 961632, hash: HASH_B, enforces: true,
        avg_interval_sec: null, interval_blocks: 0,
        seconds_since_last_block: 604800, blocks_since_split: 0 } } }) },

  "cadenas reunificadas":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(), chain: chain({ state: "reunified" }), nodes: nodes() },

  "un solo nodo configurado":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(),
      chain: chain({ extra: { single_node: true, majority: undefined, minority: undefined,
        nodes: { core: { ok: true, subversion: "/Satoshi:31.0.0/", tip: 961700, hash: HASH_A,
                         via: "clearnet", enforces: false },
                 knots: { ok: false, error: "no configurado" } } } }),
      nodes: nodes() },

  "un nodo caido":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(),
      chain: chain({ extra: { degraded: true, majority: undefined, minority: undefined,
        nodes: { core: { ok: true, subversion: "/Satoshi:31.0.0/", tip: 961700, hash: HASH_A,
                         via: "clearnet", enforces: false },
                 knots: { ok: false, error: "timeout" } } } }),
      nodes: nodes() },

  "historico con un solo periodo":
    { params, miners: miners(), history: history([1.29]), pools: pools(),
      chain: chain(), nodes: nodes() },

  "historico vacio":
    { params, miners: miners(),
      history: { ok: true, periods: [], total_blocks: 0, signalling_blocks: 0,
                 signalling_pct: 0, by_pool: {}, top_pool: null, top_pool_blocks: 0, other_pools: 0 },
      pools: pools(), chain: chain(), nodes: nodes() },

  "hitos ya pasados":
    { params, miners: miners({ scanned: 2016, sig: 1300, extra: { tip: 966000, milestones: {
        mandatory_signalling_start: { height: 961632, blocks_away: 0, approx_days: 0, passed: true },
        forced_lockin: { height: 963648, blocks_away: 0, approx_days: 0, passed: true },
        rules_active: { height: 965664, blocks_away: 0, approx_days: 0, passed: true },
        in_mandatory_window: false } } }),
      history: history([30, 45, 56, 61, 70]), pools: pools(["Foundry USA", "AntPool"]),
      chain: chain(), nodes: nodes() },

  /* La ventana obligatoria, ya abierta. Es el escenario que llega solo, y
     el dia que llegue no habra tiempo de arreglar la portada. Aqui la
     primera altura ya ha pasado y la segunda no, asi que el contador tiene
     que cambiar de destino sin que nadie lo toque. */
  "dentro de la ventana obligatoria":
    { params, miners: miners({ scanned: 800, sig: 300, extra: { tip: 962500, milestones: {
        mandatory_signalling_start: { height: 961632, blocks_away: 0, approx_days: 0, passed: true },
        forced_lockin: { height: 963648, blocks_away: 1148, approx_days: 8.0, passed: false },
        rules_active: { height: 965664, blocks_away: 3164, approx_days: 22.0, passed: false },
        in_mandatory_window: true } } }),
      history: history([1.29, 3.4, 12.1, 28.0, 44.2]), pools: pools(["Ocean", "Foundry USA"]),
      chain: chain(), nodes: nodes() },

  "sondeo de nodos sin resultados":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(), chain: chain(),
      nodes: { ok: false, error: "Sin semillas sondeables entre los peers de los nodos." } },

  "un solo nodo alcanzado":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(), chain: chain(),
      nodes: nodes({ total: 1, extra: { by_client: { Core: 1 }, pct: { Core: 100 },
        by_network: { ipv4: 1 }, by_rules: { undeclared: 1 }, pct_rules: { undeclared: 100 } } }) },

  "pools no responde":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: { ok: false, error: "timeout" }, chain: chain(), nodes: nodes() },

  "todo caido":
    { params: null, miners: { ok: false, error: "RPC no responde" },
      history: { ok: false, error: "RPC no responde" },
      pools: { ok: false, error: "RPC no responde" },
      chain: { ok: false, error: "RPC no responde" },
      nodes: { ok: false, error: "RPC no responde" } },

  "sondeo con cero nodos alcanzados":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(), chain: chain(),
      nodes: nodes({ total: 0, extra: { by_client: {}, pct: {}, by_network: {},
        by_rules: {}, pct_rules: {}, seeds_used: 0 } }) },

  /* El hito a un dia y a un año.
     Existe la comprobacion de "1 días" desde hace tiempo y nunca habia
     saltado, porque ningun escenario producia exactamente uno. Se vio en
     produccion, en pantalla, a dos dias del hito: "1 días". Una
     comprobacion sin un escenario que la dispare no protege de nada. */
  "el proximo hito esta a un dia, y otro a un año":
    { params, miners: miners({ scanned: 1900, sig: 40, extra: { milestones: {
        mandatory_signalling_start: { height: 961632, blocks_away: 190, approx_days: 1.3, passed: false },
        forced_lockin: { height: 963648, blocks_away: 2206, approx_days: 365.25, passed: false },
        rules_active: { height: 965664, blocks_away: 4222, approx_days: 730.5, passed: false },
        in_mandatory_window: false } } }),
      history: history([0.3, 0.7, 0.4, 0.9, 1.2]),
      pools: pools(["Ocean"]), chain: chain(), nodes: nodes() },

  /* El nodo BIP-110 congelado SIN separacion.
     Es lo que ocurre primero al llegar la altura obligatoria: ese nodo solo
     acepta bloques que señalicen, no hay ninguno, y se queda quieto mientras
     el otro avanza. El hash a la altura comun sigue coincidiendo, asi que el
     estado es pre_split y es correcto. Lo que no puede pasar es que la
     pantalla se quede en "los dos nodos coinciden" y nada mas. */
  "el nodo BIP-110 congelado, pero sin separacion":
    { params, miners: miners({ scanned: 1990, sig: 51 }),
      history: history([0.3, 0.7, 0.4, 0.9, 1.2]),
      pools: pools(["Ocean"]), nodes: nodes(),
      chain: chain({ extra: {
        height_gap: 70, common_height: 961631, lagging: "knots",
        nodes: {
          core: { ok: true, subversion: "/Satoshi:31.1.0/", tip: 961701,
                  hash: HASH_A, chainwork: "0f", via: "tor", enforces: false },
          knots: { ok: true, subversion: "/Satoshi:29.4.0/Knots:20260508/",
                   tip: 961631, hash: HASH_A, chainwork: "0a", via: "tor",
                   enforces: true, seconds_since_last_block: 41400 },
        } } }) },

  /* Separadas, y en ESTA cadena ya no señaliza nadie.
     Es lo que pasa siempre despues del corte: quien señaliza mina en la otra
     rama, asi que la cuenta de esta baja a cero sola. Con cero, el recorrido
     llegaba a decir que no habria cadena minoritaria que medir mientras la
     seccion de arriba la estaba midiendo. Visto en produccion el 2026-08-08. */
  "separadas, y en esta cadena ya no señaliza nadie":
    { params, miners: miners({ scanned: 20, sig: 0, extra: {
        share_source: "observed", milestone_projection: proyeccion(0.0248) } }),
      history: history([0.3, 0.7, 0.4, 0.9, 1.2]),
      pools: pools(["Ocean"]), nodes: nodes(), chain: chain({ state: "split" }) },

  /* El desfase entre las dos caches.
     La cuota medida entra al recalcular /api/miners, y su cache dura
     minutos. Recien arrancado el contenedor llega con la cuota señalizada
     (cero, porque quien señaliza mina en la otra rama) y con la separacion
     ya detectada. Esa combinacion es la que imprimia "no habria cadena
     minoritaria" teniendola medida arriba. Visto en produccion el
     2026-08-09, cinco minutos despues de un despliegue. */
  "separadas, pero la proyeccion todavia va con la cuota vieja":
    { params, miners: miners({ scanned: 20, sig: 0 }),
      history: history([0.3, 0.7, 0.4, 0.9, 1.2]),
      pools: pools(["Ocean"]), nodes: nodes(), chain: chain({ state: "split" }) },

  "umbral ya cumplido en este periodo":
    { params, miners: miners({ scanned: 1500, sig: 1200,
        byPool: { "Foundry USA": 700, AntPool: 500 } }),
      history: history([12, 25, 38, 49, 57]),
      pools: pools(["Foundry USA", "AntPool"]), chain: chain(), nodes: nodes() },

  "senalizacion al 100%":
    { params, miners: miners({ scanned: 2016, sig: 2016,
        byPool: { "Foundry USA": 1000, AntPool: 1016 } }),
      history: history([88, 92, 96, 99, 100]),
      pools: pools(["Foundry USA", "AntPool", "F2Pool", "ViaBTC", "SpiderPool",
                    "Ocean", "MARA Pool", "Luxor", "SecPool", "Binance Pool"]),
      chain: chain(), nodes: nodes() },

  "cadena minoritaria parada, cero bloques desde el corte":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(),
      chain: chain({ state: "split", extra: { minority: { node: "knots", tip: 961632,
        hash: HASH_B, enforces: true, avg_interval_sec: null, blocks_since_split: 0 } } }),
      nodes: nodes() },

  "params no responde pero el resto si":
    { params: null, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(), chain: chain(), nodes: nodes() },

  "pool desconocido es el que mas señaliza":
    { params, miners: miners({ byPool: { Desconocido: 7 } }),
      history: history([0.35, 0.79, 0.45, 0.99, 1.29], { Desconocido: 60, Ocean: 18 }),
      pools: pools(["Desconocido"]), chain: chain(), nodes: nodes() },

  "historico con 12 periodos":
    { params: Object.assign({}, params, { history_periods: 12 }),
      miners: miners(),
      history: history([0.1, 0.3, 0.2, 0.6, 0.9, 1.1, 0.8, 1.4, 2.2, 3.1, 4.0, 5.2]),
      pools: pools(), chain: chain(), nodes: nodes() },

  "el servidor esta calculando por primera vez":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: {ok: false, computing: true, error: "calculando"},
      chain: chain(),
      nodes: {ok: false, computing: true, error: "calculando"} },

  "datos viejos mientras se refresca":
    { params, miners: miners(),
      history: Object.assign(history([0.35, 0.79, 0.45, 0.99, 1.29]), {stale: true, stale_seconds: 4200}),
      pools: Object.assign(pools(), {stale: true, stale_seconds: 4200}),
      chain: chain(),
      nodes: Object.assign(nodes(), {stale: true, stale_seconds: 4200}) },

  "el CDN devuelve un error en vez de JSON":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: {ok: false, http: 524, error: "El servidor tardo demasiado"},
      chain: chain(), nodes: {ok: false, http: 502, error: "error 502"} },

  // --- el dia de la separacion, situaciones que ocurriran de verdad ---
  "el nodo BIP-110 se queda parado tras la separacion":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(),
      chain: chain({ state: "split", extra: {
        nodes: { core: { ok: true, subversion: "/Satoshi:31.0.0/", tip: 962400,
                         hash: HASH_A, chainwork: "0f", via: "tor", enforces: false },
                 knots: { ok: true, subversion: "/Satoshi:29.3.0/Knots:20260508/",
                          tip: 961633, hash: HASH_B, chainwork: "01", via: "tor", enforces: true } },
        majority: { node: "core", tip: 962400, hash: HASH_A, enforces: false,
                    avg_interval_sec: 601, blocks_since_split: 768 },
        minority: { node: "knots", tip: 961633, hash: HASH_B, enforces: true,
                    avg_interval_sec: null, blocks_since_split: 1 } } }),
      nodes: nodes() },

  "la cadena minoritaria acumula mas trabajo que la mayoritaria":
    { params, miners: miners({ scanned: 2016, sig: 1400 }),
      history: history([20, 35, 48, 56, 62]),
      pools: pools(["Foundry USA", "AntPool", "F2Pool"]),
      chain: chain({ state: "split", extra: {
        majority: { node: "knots", tip: 962500, hash: HASH_B, enforces: true,
                    avg_interval_sec: 610, blocks_since_split: 868 },
        minority: { node: "core", tip: 961700, hash: HASH_A, enforces: false,
                    avg_interval_sec: 4200, blocks_since_split: 68 } } }),
      nodes: nodes() },

  "separacion detectada pero un nodo cayo despues":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(),
      chain: chain({ state: "split", extra: { degraded: true,
        majority: undefined, minority: undefined,
        nodes: { core: { ok: true, subversion: "/Satoshi:31.0.0/", tip: 962400,
                         hash: HASH_A, via: "tor", enforces: false },
                 knots: { ok: false, error: "sin respuesta en 35s" } } } }),
      nodes: nodes() },

  "un nodo no responde y el error llega crudo":
    { params, miners: miners(), history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: pools(),
      chain: { ok: false, stale: true, stale_seconds: 118, error: "'knots'" },
      nodes: nodes() },

  "nombres de pool larguisimos":
    { params, miners: miners({ byPool: { "Pool con un nombre absurdamente largo que no cabe": 7 } }),
      history: history([0.35, 0.79, 0.45, 0.99, 1.29]),
      pools: (() => { const p = pools(); p.pools[0].pool = "Pool con un nombre absurdamente largo que no cabe"; return p; })(),
      chain: chain(), nodes: nodes() },
};

/* -------------------------------------------------------------- revisiones */
const VISTAS = ["pre_split", "split", "reunified"];
let fallos = 0;

/* Comprueba que un texto del diccionario esta en pantalla, SIN atarse a
   como este redactado. Se coge la plantilla de la clave, se parte por los
   marcadores y se busca el trozo literal mas largo. Asi reescribir un
   texto no rompe la prueba, pero cambiar la logica si. */
function usaClave(panel, salida, clave) {
  const plantilla = panel.t(clave);
  const trozos = plantilla.split(/\{[a-zA-Z][a-zA-Z0-9_]*\}/)
                          .map(x => x.trim()).filter(x => x.length > 8);
  if (!trozos.length) return salida.includes(plantilla);
  trozos.sort((a, b) => b.length - a.length);
  return salida.includes(trozos[0]);
}

// Cuantas veces sale el texto de una clave. Hace falta cuando la misma
// frase se pinta en las dos tarjetas: buscar si "aparece" daba por bueno un
// panel al que le faltaba la suya, porque la del otro tapaba el hueco.
function vecesClave(panel, salida, clave) {
  const plantilla = panel.t(clave);
  const trozos = plantilla.split(/\{[a-zA-Z][a-zA-Z0-9_]*\}/)
                          .map(x => x.trim()).filter(x => x.length > 8);
  const aguja = trozos.length ? trozos.sort((a, b) => b.length - a.length)[0] : plantilla;
  return salida.split(aguja).length - 1;
}

function revisar(nombre, lang, vista, salida, datos, panel, dom) {
  const err = m => { console.log(`  FALLO [${nombre} | ${lang} | ${vista}] ${m}`); fallos++; };

  /* "Se esta calculando" NO es un error, y no puede verse como uno.
     El servidor manda su mensaje en castellano y con ok:false. Cinco
     renderizadores miraban solo ok y lo pintaban en rojo con el texto crudo,
     asi que un arranque en frio se veia como averia y en el idioma
     equivocado. Visto en produccion el 2026-08-08. */
  for (const [cual, p] of Object.entries(datos)) {
    if (!p || !p.computing) continue;
    if (!usaClave(panel, salida, "computing"))
      err(`${cual} esta calculando y no se dice con el texto traducido`);
    if (p.error && salida.includes(p.error))
      err(`${cual} esta calculando y sale el mensaje crudo del servidor`);
  }

  /* El heroe.
     Es la parte de la pagina que mucha gente va a leer entera y sin bajar,
     asi que se comprueba aparte y no basta con que el resto pase.
     Tres cosas: que exista siempre, que no contradiga al resto de la
     pagina, y que no promocione de nivel una estimacion. */
  const hero = ((dom.els.herostat && dom.els.herostat._html) || "") +
               ((dom.els.herocd   && dom.els.herocd._html)   || "");

  /* Un nodo parado no puede pasar por "todo coincide".
     Cuando el backend marca `lagging`, el hueco ya no es ruido de
     propagacion, y la pantalla tiene que decirlo. Sin esto, la fase en la
     que el nodo BIP-110 se queda congelado antes de separarse se ve
     exactamente igual que un dia normal, que es el peor momento posible
     para que el panel no diga nada. */
  /* Solo en la vista que coincide con la realidad. En las otras el visitante
     esta mirando un escenario inventado, y meter ahi un dato medido seria
     justo lo que el panel no hace: mezclar niveles sin decirlo. */
  const ch = datos.chain;
  if (ch && ch.ok && ch.lagging && vista === ch.state) {
    const clave = ch.lagging === "knots" ? "lagBip110" : "lagToday";
    if (!usaClave(panel, salida, clave))
      err("un nodo va por detras y la pantalla no lo dice");
    if (!usaClave(panel, salida, "lagWhy"))
      err("se dice el retraso pero no se explica que no es una separacion");
    if (!hero.includes(panel.t(clave).split("{")[0].trim()))
      err("el retraso no llega al heroe, solo a la seccion de mas abajo");
  }
  if (!hero.trim()) {
    err("el heroe se ha quedado vacio");
  } else {
    // Ninguna fila se desmonta: o hay dato, o esqueleto, o error dicho.
    if (!/hcard/.test(hero)) err("el heroe ha perdido sus tarjetas");

    /* Las dos cifras de la cuenta atras son de niveles distintos y cada una
       lleva la suya. La regla no es "en el heroe no hay estimaciones", que
       es como estaba escrita antes de subir la cuenta atras entera: es que
       ninguna cifra se quede sin etiqueta ni herede la de al lado. Una
       estimacion sin el dato al lado significa que alguien enseño los dias
       sin decir que son un modelo. */
    const hayEst = hero.includes(panel.t("tagEst"));
    const hayDato = hero.includes(panel.t("tagData"));
    if (hayEst && !hayDato)
      err("el heroe enseña una estimacion sin el dato verificable al lado");

    /* Con un nodo mudo, el heroe NO puede decir que coinciden.
       Nadie lo ha medido. La seccion de mas abajo si avisaba, pero el heroe
       es lo que lee todo el mundo y afirmaba lo contrario. */
    const cd = datos.chain;
    if (cd && cd.ok && (cd.degraded || cd.single_node)) {
      if (hero.includes(panel.t("oneChainKicker")))
        err("el heroe afirma que los nodos coinciden sin poder compararlos");
      /* Y tampoco lleva etiqueta de dato verificable: la ausencia de una
         comparacion no es una comparacion. Se mira solo la tarjeta del
         estado, porque la cuenta atras de al lado si es dato verificable y
         lleva la suya con todo el derecho. */
      const tarjeta = (dom.els.herostat && dom.els.herostat._html) || "";
      if (tarjeta.includes(panel.t("tagData")))
        err("el heroe etiqueta como dato verificable una comparacion que no ha podido hacer");
    }

    /* Con las cadenas separadas, la cuenta de señalizacion cambia de
       significado: se mide sobre la cadena de hoy, y quien señaliza mina en
       la otra, asi que tiende a cero sola. Sin decirlo se lee como "ya no
       señaliza nadie", que es falso. */
    if (datos.chain && datos.chain.ok && datos.chain.state === "split" &&
        !usaClave(panel, salida, "mSplitBody"))
      err("cadenas separadas y la cuenta de señalizacion no dice sobre cual se mide");

    const c = datos.chain;
    if (c && c.ok && !c.single_node && !c.degraded) {
      const una = panel.t("oneChainKicker");
      if (vista === "split" && hero.includes(una))
        err("el heroe dice que hay una sola cadena mirando las cadenas separadas");
      /* Y con dos cadenas, la calma va pegada al susto: quien lee que se ha
         partido necesita saber ahi mismo que a el no le cambia nada. */
      if (vista === "split" && !hero.includes(panel.t("splitStillYours")))
        err("el heroe dice que hay dos cadenas y no dice que no hay que hacer nada");
      /* Y con una separacion medida, las dos huellas del corte se enseñan.
         Son la unica prueba de que hay dos cadenas y lo que permite a
         cualquiera comprobarlo contra su nodo. Sin ellas el panel pide que
         le crean. */
      /* Y con una separacion medida, la pagina NO puede decir en ningun
         sitio que no hay cadena minoritaria que medir. La habia cuatro
         secciones mas arriba, con sus bloques y su ritmo. */
      /* "Las cuentas todavia dan" se lee como "aun puede activarse". Con las
         cadenas separadas, los bloques que llevarian la marca se estan
         minando en la otra, asi que esa nota tiene que decirlo. La caja
         grande de al lado sigue diciendo "en teoria, si", y sola es
         justamente la frase que este proyecto ya tuvo que corregir una vez. */
      const mi2 = datos.miners;
      if (cd.state === "split" && mi2 && mi2.ok && mi2.threshold_reachable &&
          mi2.signalling_blocks < mi2.threshold_blocks) {
        if (!usaClave(panel, salida, "mReachNoteSplit"))
          err("cadenas separadas y el umbral se explica como si nada hubiera cambiado");
        if (usaClave(panel, salida, "mReachNote"))
          err("cadenas separadas y ademas se imprime la nota del umbral sin separacion");
      }

      /* Y el heroe tiene que decir SOBRE QUE CADENA cuenta el hito. Con dos
         cadenas, "faltan N bloques" sin decir de cual no significa nada, y
         la respuesta que casi todo el mundo busca es la de la cadena
         BIP-110, que es la unica donde ese hito ocurre. */
      if (cd.state === "split" && cd.minority && cd.minority.tip != null &&
          !usaClave(panel, salida, "cdOnBip"))
        err("hay dos cadenas y el heroe no dice en cual cuenta el proximo hito");

      /* Y un plazo sacado de un puñado de bloques se dice con esa cara. La
         cifra grande de al lado es un recuento exacto; esta es una
         extrapolacion sobre dos bloques, y sin decirlo las dos se leen
         igual de firmes. */
      if (cd.state === "split" && cd.minority &&
          cd.minority.blocks_since_split != null &&
          cd.minority.blocks_since_split < 12 &&
          !usaClave(panel, salida, "cdFewBlocks"))
        err("se da un plazo sacado de pocos bloques sin decir sobre cuantos va");

      if (cd.state === "split" && usaClave(panel, salida, "strNever"))
        err("hay dos cadenas medidas y el recorrido dice que no hay ninguna que medir");

      if (vista === "split" && cd.state === "split" && cd.split_hashes) {
        const trozo = (cd.split_hashes.knots || "").slice(-10);
        if (trozo && !salida.includes(trozo))
          err("hay separacion medida y no se enseña la huella del bloque divergente");
      }
      if (vista === "pre_split" && !hero.includes(una))
        err("el heroe no dice en que estado esta la cadena");
    }

    /* La cifra del heroe y la de la seccion de la cuenta atras salen del
       mismo calculo a proposito. Dos numeros distintos en la misma pagina
       para el mismo hito seria peor que no enseñar ninguno. */
    const mi = datos.miners;
    if (mi && mi.ok && mi.milestones) {
      const orden = ["mandatory_signalling_start", "forced_lockin", "rules_active"];
      const clave = orden.find(k => !((mi.milestones[k] || {}).passed));
      if (clave) {
        /* Con las cadenas separadas, el hito se cuenta en la cadena donde
           ocurre, que es la del BIP-110: ese despliegue no existe en la
           otra. Asi que la cifra correcta no es blocks_away, que va sobre
           la cadena mayoritaria, sino la distancia desde la punta de la
           minoritaria. */
        const hm = mi.milestones[clave] || {};
        const mn = (datos.chain && datos.chain.ok && datos.chain.state === "split")
                 ? (datos.chain.minority || null) : null;
        const n = (mn && mn.tip != null && hm.height != null)
                ? Math.max(0, hm.height - mn.tip) : hm.blocks_away;
        /* Sin separadores de millar: el panel escribe 1.733 en castellano y
           1,733 en ingles, asi que comparar el numero crudo fallaba siempre.
           Se comparan digitos con digitos. */
        const soloDigitos = hero.replace(/[.,  \s]/g, "");
        if (n != null && !soloDigitos.includes(String(n)))
          err(`el heroe no enseña los ${n} bloques que faltan para el proximo hito`);
        // Con la cuenta atras arriba, las dos etiquetas tienen que estar.
        if (!hayEst || !hayDato)
          err("la cuenta atras del heroe no lleva sus dos etiquetas epistemicas");
      }
    }
  }

  const marc = salida.match(/\{[a-zA-Z][a-zA-Z0-9_]*\}/g);
  if (marc) err(`marcadores sin rellenar: ${[...new Set(marc)].join(", ")}`);
  // "1 años" y "1 years" salieron en el eje de los hitos. Es concordancia,
  // no logica, pero se lee mal y ninguna otra comprobacion la mira.
  for (const basura of ["undefined", "NaN", "[object Object]", "Infinity", "null%",
                        "1 años", "1 years", "1 días", "1 days"]) {
    if (salida.includes(basura)) err(`aparece "${basura}" en pantalla`);
  }

  // Coherencia texto/dato: no afirmar cosas que los datos desmienten.
  const m = datos.miners, h = datos.history, p = datos.pools;

  /* El ritmo de cada cadena, y su base.
     Un intervalo medio no distingue "va despacio" de "esta parada": una rama
     que dejo de producir hace un mes conserva intacta la media que tenia. Y
     recien separadas las cadenas esa media sale de uno o dos intervalos, que
     no es lo mismo que sacarla de 144. Las dos cosas tienen que llegar a la
     pantalla o el panel esta dando una cifra por mas solida de lo que es. */
  if (vista === "split" && datos.chain && datos.chain.ok) {
    const min = datos.chain.minority || {}, maj = datos.chain.majority || {};
    // Se cuenta, no se busca: la misma frase va en las dos tarjetas, y con
    // buscar bastaba que la pintara una para dar por buena la otra.
    const conFecha = [min, maj].filter(s => s.seconds_since_last_block != null).length;
    if (vecesClave(panel, salida, "lastBlock") < conFecha) {
      err(`${conFecha} cadenas tienen fecha de ultimo bloque y solo se pinta ` +
          `${vecesClave(panel, salida, "lastBlock")} vez/veces`);
    }
    const sinBloques = usaClave(panel, salida, "paceNoBlocks");
    const conBase = usaClave(panel, salida, "paceBase");
    if (min.interval_blocks === 0) {
      if (!sinBloques) err("la rama no tiene bloques propios y no lo dice");
      if (min.avg_interval_sec != null) err("sin bloques propios y aun asi da un ritmo");
    } else {
      // Con 144 bloques detras no hay que disculparse por la base, y decir
      // que no hay bloques propios cuando los hay seria mentir al reves.
      if (sinBloques && maj.interval_blocks >= 12) {
        err("dice que no hay bloques propios cuando la mayoritaria tiene 144");
      }
      if (min.interval_blocks != null && min.interval_blocks < 12 && !conBase) {
        err(`la media va sobre ${min.interval_blocks} bloques y no lo dice`);
      }
    }
  }

  /* El contador de cabecera.
     Es lo primero que se ve, asi que equivocarse ahi es equivocarse en lo
     unico que mucha gente va a leer. Tres invariantes:
       - apunta al PRIMER hito no alcanzado, no a uno escrito a mano;
       - si ya han pasado los tres, no cuenta nada;
       - nunca cuenta hacia atras. */
  if (m && m.ok && m.milestones) {
    const ms = m.milestones;
    const orden = [["mandatory_signalling_start", "cdWhat1"],
                   ["forced_lockin",              "cdWhat2"],
                   ["rules_active",               "cdWhat3"]];
    const sig = orden.find(([k]) => !((ms[k] || {}).passed));
    const esperada = sig ? sig[1] : "cdAllPassed";
    for (const k of ["cdWhat1", "cdWhat2", "cdWhat3", "cdAllPassed"]) {
      const esta = usaClave(panel, salida, k);
      if (k === esperada && !esta) err(`el contador deberia apuntar a ${k} y no lo hace`);
      if (k !== esperada && esta) err(`el contador apunta a ${esperada} y ademas dice ${k}`);
    }
    if (sig && !(ms[sig[0]].blocks_away > 0)) {
      err(`el contador apunta a ${sig[0]} con ${ms[sig[0]].blocks_away} bloques`);
    }
    // El aviso de que la ventana obligatoria puede no existir. Sale de
    // deploymentstatus.h: si el umbral se cumple antes, no hay ventana.
    const cumbral = m.threshold_blocks != null && m.signalling_blocks >= m.threshold_blocks;
    const tocaAviso = !!sig && sig[0] === "mandatory_signalling_start" && cumbral;
    const dice = usaClave(panel, salida, "cdLockNote");
    if (tocaAviso && !dice) err("umbral cumplido y el contador no avisa de que la ventana puede no existir");
    if (!tocaAviso && dice) err("avisa de que la ventana puede no existir sin que el umbral este cumplido");
    // Estar DENTRO de la ventana obligatoria hay que decirlo: es el momento
    // en que las cadenas pueden separarse, y es el unico de los tres que el
    // lector nota mirando el panel y no el calendario.
    const enVentana = usaClave(panel, salida, "cdInWindow");
    if (ms.in_mandatory_window && !enVentana) err("estamos dentro de la ventana obligatoria y no lo dice");
    if (!ms.in_mandatory_window && enVentana) err("dice que estamos dentro de la ventana obligatoria y no lo estamos");
  }

  if (m && m.ok) {
    const cumplido = m.signalling_blocks >= m.threshold_blocks;
    const esperada = cumplido ? "reachMet" : (m.threshold_reachable ? "reachYes" : "reachNo");
    for (const k of ["reachMet", "reachYes", "reachNo"]) {
      const esta = salida.includes(panel.t(k));
      if (k === esperada && !esta) err(`el umbral esta en '${esperada}' y no lo dice`);
      if (k !== esperada && esta) err(`el umbral esta en '${esperada}' y ademas dice '${k}'`);
    }
    // Los hitos estirados: el texto tiene que decir el escenario correcto,
    // y con cuota 0 no puede imprimirse un plazo, tiene que decir "nunca".
    const pr = m.milestone_projection;
    if (pr) {
      const sh = pr.share_pct, thr = m.threshold_pct;
      // Con la cuota MEDIDA (ya hay separacion) el texto es otro: no se
      // supone la cuota, se cuenta, y decirlo cambia lo que la frase afirma.
      const medida = m.share_source === "observed";
      const normal = medida ? "strLeadObs" : "strLead";
      /* Y hay un cuarto estado: separacion ya detectada pero la proyeccion
         todavia con la cuota vieja. Ahi no se afirma nada, se dice que se
         esta rehaciendo. Decir "nunca" seria contradecir a la seccion de
         arriba, que tiene la cadena minoritaria medida. */
      const desfase = datos.chain && datos.chain.ok &&
                      datos.chain.state === "split" && sh <= 0 && !medida;
      const cual = desfase ? "strRecalc"
                 : (sh <= 0 && !medida) ? "strNever"
                 : (sh >= thr ? "strNoSplit" : normal);
      for (const k of ["strNever", "strNoSplit", "strLead", "strLeadObs", "strRecalc"]) {
        const esta = usaClave(panel, salida, k);
        if (k === cual && !esta) err(`la cuota es ${sh}% y no usa ${k}`);
        if (k !== cual && esta) err(`la cuota es ${sh}% y ademas usa ${k}`);
      }
      // Se cuenta la MARCA, no la palabra: "nunca" sale en otros textos de
      // la pagina, asi que buscarla daba positivo siempre y la comprobacion
      // pasaba aunque el plazo se imprimiera como un numero.
      const sinPlazo = desfase ? 0 : pr.milestones.filter(x => !x.reachable).length;
      const marcados = (salida.match(/class="v is-never"/g) || []).length;
      if (marcados !== sinPlazo) {
        err(`${sinPlazo} hitos inalcanzables pero ${marcados} marcados sin plazo`);
      }
      // Ningun hito puede tardar MENOS en la cadena minoritaria.
      for (const x of pr.milestones) {
        if (x.slowdown !== null && x.slowdown < 1) {
          err(`el hito ${x.key} llegaria antes en la cadena minoritaria (${x.slowdown}x)`);
        }
      }
    }
    const firmantes = Object.keys(m.signalling_by_pool || {}).length;
    if (firmantes === 0 && !/No block has signalled|Todavía no ha señalizado/.test(salida)) {
      err("nadie señaliza y no lo dice");
    }
  }
  if (h && h.ok && h.periods.length >= 2) {
    const d = h.periods[h.periods.length - 1].pct - h.periods[0].pct;
    const esperada = Math.abs(d) < 0.5 ? "trendFlat" : (d > 0 ? "trendUp" : "trendDown");
    if (!usaClave(panel, salida, esperada)) {
      err(`la tendencia es ${d.toFixed(2)} y no se usa ${esperada}`);
    }
    for (const otra of ["trendFlat", "trendUp", "trendDown"]) {
      if (otra !== esperada && usaClave(panel, salida, otra)) {
        err(`la tendencia es ${d.toFixed(2)} y ademas se usa ${otra}`);
      }
    }
  }
  if (h && h.ok && h.periods.length < 2 && !usaClave(panel, salida, "trendNone")) {
    err("sin historico suficiente y no usa trendNone");
  }
  // El historico ya no es prosa: son nombres. Si señalizo mas de un pool,
  // tienen que aparecer TODOS por nombre, no un recuento suelto.
  if (h && h.ok && h.signalling_blocks && h.by_pool) {
    for (const nombre of Object.keys(h.by_pool)) {
      if (!salida.includes(nombre)) err(`el pool ${nombre} señalizo y no aparece por nombre`);
    }
    const varios = Object.keys(h.by_pool).length > 1;
    if (!usaClave(panel, salida, varios ? "histSeveral" : "histOnlyOne")) {
      err(`${Object.keys(h.by_pool).length} pools en el historico y el remate no cuadra`);
    }
  }
  if (p && p.ok) {
    const firman = p.pools.filter(r => r.signalling_blocks > 0);
    if (firman.length > 1 && usaClave(panel, salida, "coalitionBody")) {
      err(`firman ${firman.length} pools y dice que solo uno`);
    }
    // Todo pool que señaliza en el periodo en curso, por nombre.
    const m2 = datos.miners;
    if (m2 && m2.ok) {
      for (const nombre of Object.keys(m2.signalling_by_pool || {})) {
        if (!salida.includes(nombre)) err(`${nombre} señaliza este periodo y no aparece`);
      }
    }
  }
}

console.log("=".repeat(70));
console.log("BANCO DE PRUEBAS DE LA INTERFAZ");
console.log("=".repeat(70));

for (const [nombre, datos] of Object.entries(ESCENARIOS)) {
  for (const lang of ["en", "es"]) {
    for (const vista of VISTAS) {
      const dom = nuevoDom();
      let panel;
      try {
        panel = cargarPanel(dom);
        Object.assign(panel.DATA, datos);
        panel.setLang(lang);
        panel.setView(vista);
        /* El heroe se borra aqui a proposito.
           setView() tambien lo pinta, asi que sin esta linea la comprobacion
           del heroe pasaba aunque renderAll() dejara de pintarlo. Y ese es
           justo el fallo que llega a produccion: en la pagina real setView()
           solo se ejecuta si el visitante pulsa el conmutador de escenarios,
           mientras que renderAll() es el camino de todos los demas.
           Comprobado rompiendolo: sin esta linea, quitar el heroe de
           renderAll() no falla ni un escenario. */
        if (dom.els.herostat) dom.els.herostat._html = "";
        if (dom.els.herocd) dom.els.herocd._html = "";
        panel.renderAll();
      } catch (e) {
        console.log(`  FALLO [${nombre} | ${lang} | ${vista}] excepcion: ${e.message}`);
        fallos++;
        continue;
      }
      const salida = [
        ...Object.values(dom.els).map(e => e._html + " " + e._text),
        ...dom.conDataK.map(e => e._text),
      ].join("\n");
      revisar(nombre, lang, vista, salida, datos, panel, dom);
    }
  }
  console.log(`  probado: ${nombre}`);
}

console.log("=".repeat(70));
console.log(`${Object.keys(ESCENARIOS).length} escenarios x 2 idiomas x ${VISTAS.length} vistas`);
console.log(fallos === 0 ? "SIN FALLOS" : `${fallos} FALLOS`);
process.exit(fallos ? 1 : 0);
