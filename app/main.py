"""
BIP-110 Observer: panel de señalización.

Endpoints con epistemologia distinta a proposito:
  /api/miners   -> dato verificable contra tu propio nodo
  /api/pools    -> estimacion sobre muestra, medida contra tu nodo
  /api/nodes    -> muestra sesgada, etiquetada como tal
"""

import os
import re
import json
import time
import threading
from flask import Flask, jsonify, request, send_from_directory

from rpc import BitcoinRPC
import signaling
import pools as poolsmod
import crawler as crawlermod

app = Flask(__name__, static_folder="static")

CACHE_DIR = os.environ.get(
    "CACHE_DIR",
    "/data" if os.path.isdir("/data") else os.path.join(os.path.dirname(__file__), "data")
)
try:
    os.makedirs(CACHE_DIR, exist_ok=True)
except OSError:
    CACHE_DIR = None  # la cache es en memoria; no es critico

_cache = {}
_lock = threading.Lock()

TTL = {
    "miners": int(os.environ.get("MINERS_TTL", "300")),
    "pools": int(os.environ.get("POOLS_TTL", "3600")),
    "nodes": int(os.environ.get("NODES_TTL", "3600")),
    "chains": int(os.environ.get("CHAINS_TTL", "60")),
    # Los periodos cerrados no cambian; el TTL solo controla cada cuanto se
    # comprueba si ha cerrado uno nuevo.
    "history": int(os.environ.get("HISTORY_TTL", "3600")),
}
POOLS_SAMPLE = int(os.environ.get("POOLS_SAMPLE", "500"))
# Un endpoint de salud que tarda medio minuto no sirve como endpoint de
# salud: el propio supervisor lo da por muerto. Pero el tope tiene que ir
# con la ruta: por Tor un nodo tarda segundos y la latencia varia mucho de
# una peticion a otra, asi que un tope pensado para la red local marca como
# caido un nodo que solo iba lento ese rato.
HEALTH_TIMEOUT_CLEARNET = int(os.environ.get("HEALTH_TIMEOUT", "12"))
HEALTH_TIMEOUT_TOR = int(os.environ.get("HEALTH_TIMEOUT_TOR", "150"))
# Intentos por nodo antes de darlo por caido. Ver el comentario de mirar().
HEALTH_INTENTOS = int(os.environ.get("HEALTH_INTENTOS", "2"))
# OJO CON ESTE NUMERO, que ya nos costo una noche.
#
# El 2026-08-08, con la ventana obligatoria recien abierta, el panel dijo
# durante horas que el nodo BIP-110 no respondia. Respondia perfectamente: lo
# que pasaba es que por el servicio oculto tardaba mas de lo que le
# dabamos. El propio Tor avisa de que insiste "120 seconds ... giving up",
# asi que cualquier plazo por debajo de eso convierte una conexion lenta en
# un nodo caido, y el panel acaba publicando que no ve algo que si ve.
#
# Regla: estos plazos van POR ENCIMA de los 120 s de Tor, nunca por debajo.
# No cuesta latencia al visitante porque el calculo va en un hilo aparte y
# la peticion devuelve lo que haya en cache.
CHAIN_TIMEOUT = int(os.environ.get("CHAIN_TIMEOUT", "240"))


def _health_timeout():
    for name in NODE_NAMES:
        if any(transport_of(u) == "tor" for u in _node_urls(name)):
            return HEALTH_TIMEOUT_TOR
    return HEALTH_TIMEOUT_CLEARNET


# Dos nodos, a proposito.
#
#   core   -> nodo sin BIP-110. Sigue la cadena mayoritaria pase lo que pase.
#             Es el canonico y el que responde por defecto.
#   knots  -> nodo que aplica BIP-110. A partir del bloque 961.632 rechaza
#             los bloques que no señalicen bit 4, asi que puede acabar en la
#             cadena minoritaria.
#
# Antes del 961.632 los dos ven la misma cadena. Despues no tiene por que,
# y esa diferencia es justamente lo que el panel quiere enseñar. Por eso no
# se mezclan nunca: cada cifra dice de que nodo sale.
NODE_NAMES = ("core", "knots")
DEFAULT_NODE = "core"


# Cada nodo puede tener dos direcciones, clearnet y Tor. Se usa UNA, la
# primera que responda, y si deja de responder se prueba la otra. No se
# consultan las dos a la vez: seria el doble de trabajo para el mismo dato.
#
# El orden es a proposito: clearnet primero porque es mucho mas rapida, y
# Tor como respaldo. En el VPS la clearnet no llegara al nodo de casa, asi
# que fallara rapido y se quedara en Tor.
_ENV_URLS = {
    "core":  ("BTC_RPC_URL", "BTC_RPC_TOR_URL"),
    "knots": ("BTC_RPC_URL_KNOTS", "BTC_RPC_TOR_URL_KNOTS"),
}
RPC_PICK_TTL = int(os.environ.get("RPC_PICK_TTL", "900"))
RPC_PROBE_TIMEOUT = int(os.environ.get("RPC_PROBE_TIMEOUT", "6"))
_rpc_pick = {}


def _normalize_url(url):
    """
    Una direccion sin esquema es un error facil de cometer y dificil de
    diagnosticar: curl asume http:// y funciona, pero requests no, y suelta
    un "No connection adapters were found" que no dice nada a nadie. Se
    asume http:// y a correr.
    """
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url.rstrip("/")


def _node_urls(node):
    """Direcciones candidatas del nodo, en orden de preferencia."""
    clear, tor = _ENV_URLS.get(node, _ENV_URLS["core"])
    urls = [u for u in (_normalize_url(os.environ.get(clear)),
                        _normalize_url(os.environ.get(tor))) if u]
    if not urls and node == "core":
        urls = ["http://127.0.0.1:8332"]
    # Sin duplicados: la misma direccion dos veces solo duplica la espera.
    vistas, unicas = set(), []
    for u in urls:
        if u not in vistas:
            vistas.add(u)
            unicas.append(u)
    return unicas


def _node_creds(node):
    if node == "knots":
        return (os.environ.get("BTC_RPC_USER_KNOTS") or os.environ.get("BTC_RPC_USER", ""),
                os.environ.get("BTC_RPC_PASSWORD_KNOTS") or os.environ.get("BTC_RPC_PASSWORD", ""))
    return (os.environ.get("BTC_RPC_USER", ""), os.environ.get("BTC_RPC_PASSWORD", ""))


def _node_config(node):
    """Compatibilidad: primera url, usuario y clave."""
    urls = _node_urls(node)
    user, password = _node_creds(node)
    return (urls[0] if urls else None, user, password)


def _huella(url):
    """Identificador estable de una direccion, que no la revela."""
    import hashlib
    return hashlib.sha256((url or "").encode()).hexdigest()[:8]


def _node_configured(node):
    return bool(_node_urls(node))


def transport_of(url):
    return "tor" if url and ".onion" in url else "clearnet"


def _invalidate_pick(node):
    """La direccion elegida ha fallado: que la proxima vez se vuelva a probar."""
    _rpc_pick.pop(node, None)


def _rpc(node=DEFAULT_NODE, force=False):
    """
    Cliente RPC del nodo, eligiendo la primera direccion que responda.

    La eleccion se recuerda un rato para no sondear en cada peticion, y se
    invalida en cuanto una llamada falla, asi que un corte de la clearnet
    pasa a Tor en la siguiente peticion y no dentro de cinco minutos.
    """
    urls = _node_urls(node)
    if not urls:
        raise RuntimeError(f"El nodo '{node}' no esta configurado.")
    user, password = _node_creds(node)
    now = time.time()

    if not force:
        pick = _rpc_pick.get(node)
        if pick and now - pick[1] < RPC_PICK_TTL:
            return BitcoinRPC(url=pick[0], user=user, password=password)

    errors, last = {}, None
    for url in urls:
        # Si hay que salir por Tor y no hay SOCKS escuchando, el error que
        # sale es "Connection refused" contra el 9050, que no apunta a nada
        # y manda a buscar donde no es. Mejor decir lo que pasa de verdad.
        if transport_of(url) == "tor" and not _tor_socks_open(
                os.environ.get("TOR_HOST", "127.0.0.1"),
                int(os.environ.get("TOR_PORT", "9050"))):
            errors[url] = ("no hay ningun SOCKS de Tor escuchando en "
                           f"{os.environ.get('TOR_HOST', '127.0.0.1')}:"
                           f"{os.environ.get('TOR_PORT', '9050')}, "
                           "asi que una direccion .onion no se puede alcanzar")
            continue
        # La clearnet tiene que fallar rapido; por Tor hay que dar margen.
        timeout = RPC_PROBE_TIMEOUT if transport_of(url) == "clearnet" else 60
        try:
            probe = BitcoinRPC(url=url, user=user, password=password, timeout=timeout)
            probe.call("getblockcount")
        except Exception as e:
            errors[url] = str(e)
            last = e
            continue
        _rpc_pick[node] = (url, now)
        return BitcoinRPC(url=url, user=user, password=password)

    raise RuntimeError(
        f"Ninguna direccion del nodo '{node}' responde. Probadas: "
        + "; ".join(f"{u} -> {errors.get(u, 'sin respuesta')}" for u in urls)
    ) from last


def _active_url(node):
    pick = _rpc_pick.get(node)
    return pick[0] if pick else None


def _pick_node():
    """Nodo pedido en la query. Cualquier valor raro cae en el canonico."""
    node = (request.args.get("node") or DEFAULT_NODE).lower()
    return node if node in NODE_NAMES else DEFAULT_NODE


# Endpoints que pueden tardar minutos: el sondeo del P2P, el escaneo de
# pools y el historico la primera vez. NINGUNO puede calcularse dentro de
# una peticion HTTP.
#
# Un CDN corta a los ~100 segundos y devuelve su propia pagina de error en
# HTML. El navegador intenta leerla como JSON y revienta con un error de
# sintaxis que no dice nada. Subir el timeout del proxy no arregla nada,
# porque quien corta esta por delante.
#
# Asi que estos endpoints devuelven SIEMPRE al instante: lo que haya en
# cache aunque este viejo, o un aviso de que se esta calculando. El calculo
# ocurre en segundo plano.
_computando = set()


def _lanzar_calculo(ck, builder):
    def correr():
        try:
            payload = builder()
        except Exception as e:
            payload = {"ok": False, "error": _explicar(e), "motivo": _motivo(e), "detalle": _detalle(e)}
        fallo = not payload.get("ok", False)
        with _lock:
            previo = _cache.get(ck)
            bueno = previo and previo[0].get("ok")
            if fallo and bueno:
                # Un tropiezo pasajero NO tira un dato bueno.
                #
                # Guardar el fallo encima borraba cifras correctas y ponia
                # un error en pantalla donde se podia estar sirviendo un
                # dato de hace tres minutos. Con Tor por medio eso pasa
                # cada dos por tres: un circuito que no monta no es motivo
                # para dejar de contar lo que ya se sabe.
                #
                # Se conserva la marca de tiempo ORIGINAL a proposito: asi
                # el dato sigue contando como viejo, la interfaz dice de
                # cuando es, y la siguiente peticion vuelve a intentarlo.
                conservado = dict(previo[0])
                conservado["ultimo_fallo"] = payload.get("error")
                _cache[ck] = (conservado, previo[1])
            else:
                _cache[ck] = (payload, time.time())
            _computando.discard(ck)
    threading.Thread(target=correr, daemon=True).start()


# Fallos habituales traducidos a algo que se pueda leer.
#
# El orden importa: se coge la PRIMERA que coincida, asi que lo especifico
# va antes que lo general. "max retries exceeded" aparece en casi todos los
# fallos de red, por eso va el ultimo.
#
# Los codigos son de SOCKS5 (RFC 1928, campo REP), que es como Tor cuenta
# lo que le paso. Sin traducir, al visitante le llegaba un parrafo con
# SOCKSHTTPConnectionPool y NewConnectionError dentro.
_MOTIVOS = [
    ("0x01", "tor_circuito", "Tor no ha podido establecer el circuito con el nodo"),
    ("0x02", "tor_prohibido", "Tor tiene prohibido conectar con esa direccion"),
    ("0x04", "tor_no_encuentra", "Tor no encuentra el servicio oculto del nodo"),
    ("0x05", "rechazada", "el nodo ha rechazado la conexion"),
    ("0x06", "tor_caducado", "el circuito de Tor ha caducado antes de conectar"),
    ("no hay ningun socks", "sin_tor", "no hay ningun Tor escuchando por el que salir"),
    ("401", "credenciales", "el nodo ha rechazado el usuario o la clave del RPC"),
    ("403", "prohibido", "el nodo no permite esta conexion al RPC"),
    ("connection refused", "sin_escucha", "no hay nadie escuchando en esa direccion"),
    ("timed out", "lento", "el nodo ha tardado demasiado en responder"),
    ("read timeout", "lento", "el nodo ha tardado demasiado en responder"),
    ("name or service not known", "sin_dns", "no se ha podido resolver la direccion del nodo"),
    ("no esta configurado", "sin_configurar", "ese nodo no esta configurado"),
    ("max retries exceeded", "sin_conexion", "no se ha podido conectar con el nodo"),
]
assert all(p == p.lower() for p, _, _ in _MOTIVOS), "los patrones van en minusculas"


def _explicar(e):
    """
    El motivo en una frase, para quien mira el panel.

    Antes salia el texto crudo de la excepcion, y en pantalla se leia
    "SOCKSHTTPConnectionPool(host=<nodo>, port=8332): Max retries exceeded
    ... NewConnectionError ... 0x01: General SOCKS server failure". Quien
    visita el panel no puede hacer nada con eso y no le dice lo unico que
    le importa, que es que el nodo no contesta ahora mismo.

    El detalle tecnico no se pierde: va en _detalle(), que solo sale por la
    API. La regla es la de siempre, cada dato en su sitio y ninguno se
    esconde; lo que cambia es a quien se le pone delante.
    """
    txt = _sin_direcciones(str(e).strip())
    bajo = txt.lower()
    for pista, _clave, motivo in _MOTIVOS:
        if pista in bajo:
            return motivo
    if isinstance(e, KeyError):
        # str(KeyError('knots')) es "'knots'", que no dice nada y fue lo que
        # acabo en pantalla la primera vez que un nodo tardo de mas.
        return f"falta el dato {txt} al montar la respuesta"
    return txt or type(e).__name__


def _motivo(e):
    """
    Clave estable del fallo, para que la interfaz lo traduzca.

    El texto de _explicar() esta en castellano, y servirlo tal cual dejaba
    la version inglesa del panel enseniando una frase en espaniol. Se
    devuelve la clave y que cada idioma ponga la suya, igual que hace
    crawler.classify_rules(). Si el fallo no esta en la tabla, la interfaz
    se queda con el texto, que es mejor que nada.
    """
    bajo = _sin_direcciones(str(e).strip()).lower()
    for pista, clave, _motivo in _MOTIVOS:
        if pista in bajo:
            return clave
    return None


def _detalle(e):
    """El texto crudo, ya sin direcciones. Solo para la API, nunca en pantalla."""
    return f"{_sin_direcciones(str(e).strip())} ({type(e).__name__})".strip()


_RE_ONION = re.compile(r"\b[a-z2-7]{16,60}\.onion\b", re.I)
_RE_HOST = re.compile(r"host=['\"]?[^'\"\s,)]+['\"]?", re.I)
_RE_URL = re.compile(r"https?://[^\s'\"]+", re.I)


def _sin_direcciones(txt):
    """
    Quita del texto cualquier direccion del nodo.

    Los mensajes de requests llevan el host dentro:
    "HTTPConnectionPool(host='xxxx.onion', port=8332)". /api/health y
    /api/chain son publicas, asi que ese mensaje publica el servicio oculto
    del nodo de casa justo el dia que algo falla, que es cuando nadie esta
    mirando la respuesta con lupa. La direccion no le sirve de nada a quien
    lee el panel: le sirve saber que el nodo no contesta.
    """
    txt = _RE_URL.sub("<nodo>", txt or "")
    txt = _RE_HOST.sub("host=<nodo>", txt)
    return _RE_ONION.sub("<nodo>", txt)


def _cuota_observada():
    """Cuota de la rama minoritaria MEDIDA, o None si no hay separacion.

    Bloques propios de cada rama desde el corte. No se consulta a ningun
    nodo: se lee lo que ya calculo /api/chains, asi que no cuesta ni una
    llamada mas. Si esa comparacion todavia no existe, se devuelve None y
    todo sigue como antes.
    """
    with _lock:
        e = _cache.get("chains:" + DEFAULT_NODE)
    d = e[0] if e else None
    if not d or not d.get("ok") or d.get("state") != "split":
        return None
    a = (d.get("majority") or {}).get("blocks_since_split")
    b = (d.get("minority") or {}).get("blocks_since_split")
    if not isinstance(a, int) or not isinstance(b, int) or (a + b) <= 0:
        return None
    return b / float(a + b)


def _cached_bg(key, builder, node=DEFAULT_NODE):
    """Como _cached, pero sin hacer esperar nunca a quien pregunta."""
    ck = f"{key}:{node}"
    with _lock:
        e = _cache.get(ck)
        fresco = e and time.time() - e[1] < TTL.get(key, 300)
        if fresco:
            return e[0]
        arrancar = ck not in _computando
        if arrancar:
            _computando.add(ck)
    if arrancar:
        _lanzar_calculo(ck, builder)
    if e:
        # Hay resultado viejo: se sirve, diciendo desde cuando es.
        viejo = dict(e[0])
        viejo["stale"] = True
        viejo["stale_seconds"] = int(time.time() - e[1])
        return viejo
    return {"ok": False, "computing": True,
            "error": "calculando por primera vez, puede tardar unos minutos"}


def _cached(key, builder, node=DEFAULT_NODE):
    ck = f"{key}:{node}"
    with _lock:
        e = _cache.get(ck)
        if e and time.time() - e[1] < TTL.get(key, 300):
            return e[0]
    payload = builder()
    with _lock:
        _cache[ck] = (payload, time.time())
    return payload


@app.after_request
def _cache_headers(resp):
    """
    Quien decide si una respuesta se puede cachear es la aplicacion, no el
    proxy que tenga delante.

    Sin esto, Cloudflare puede decidir por su cuenta cachear /api/* y el
    panel mostraria cifras congeladas sin fallar: no da error, simplemente
    miente, que es el peor modo de fallo posible aqui. La regla de pagina en
    Cloudflare y la del Nginx siguen puestas, pero como segunda y tercera
    capa, no como unica.
    """
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    elif request.path in ("/", "/methodology", "/metodologia"):
        # El HTML lleva los textos y la logica; los datos entran por fetch.
        # Cinco minutos en el navegador, y que revalide en los intermedios.
        resp.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/methodology")
@app.route("/metodologia")
def methodology():
    """Una sola pagina bilingue: el idioma lo elige el lector, no la ruta."""
    return send_from_directory(app.static_folder, "methodology.html")


@app.route("/robots.txt")
def robots():
    return send_from_directory(app.static_folder, "robots.txt",
                               mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    """Dos paginas. No hace falta generarlo con nada."""
    base = request.url_root.rstrip("/")
    hoy = time.strftime("%Y-%m-%d", time.gmtime())
    urls = "".join(
        f"<url><loc>{base}{p}</loc><lastmod>{hoy}</lastmod>"
        f"<changefreq>{c}</changefreq></url>"
        for p, c in (("/", "hourly"), ("/methodology", "weekly")))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           + urls + "</urlset>")
    return app.response_class(xml, mimetype="application/xml")


@app.route("/api/params")
def params():
    """
    Parametros en uso. La interfaz los pide de aqui en lugar de escribirlos
    a mano, incluidos los que "nunca cambian": el umbral del 55%, los 2016
    bloques del periodo y los 600 segundos por bloque. Clavarlos en el
    texto los convierte en una mentira el dia que alguno se toque, y nadie
    se entera porque nadie va a releer los textos buscando numeros.
    """
    bip = signaling.BIP110
    return jsonify({
        "bip": bip,
        "target_spacing": signaling.TARGET_SPACING,
        "threshold_pct": round(bip["threshold_num"] / bip["period"] * 100, 2),
        "blocks_per_day": round(86400 / signaling.TARGET_SPACING),
        "history_periods": HISTORY_PERIODS,
        "source": ("Parametros tomados de la seccion Deployment de "
                   "bip-0110.mediawiki en bitcoin/bips, v1.0.0 (Complete)."),
    })


def _build_miners(node=DEFAULT_NODE):
    try:
        rpc = _rpc(node)
        info = rpc.get_blockchain_info()
        data = signaling.analyse(rpc)
        headers = data.pop("headers")

        sig_set = set(data["signalling_heights"])
        sig_headers = [h for h in headers if h["height"] in sig_set]
        attributed = poolsmod.attribute_blocks(rpc, sig_headers) if sig_headers else []

        by_pool = {}
        for a in attributed:
            by_pool[a["pool"]] = by_pool.get(a["pool"], 0) + 1

        share = signaling.signalling_share(data)
        fuente_cuota = "signalling"

        # DESDE LA SEPARACION, LA SEÑALIZACION YA NO SIRVE PARA ESTIMAR ESTO.
        #
        # La cuota se contaba sobre la cadena canonica, y a partir del corte
        # quien señaliza mina en la OTRA, asi que aqui sale cero por
        # construccion. Con cero, la proyeccion decia que la cadena
        # minoritaria "no produciria ni un bloque" y que los hitos no
        # llegarian "nunca", mientras la seccion de arriba de la misma pagina
        # enseñaba esa cadena con sus bloques y su ritmo. Dos secciones
        # contradiciendose es peor que cualquiera de las dos por separado.
        #
        # Con las cadenas ya separadas no hay que estimar la cuota: se mide.
        # Bloques propios de cada rama desde el corte, que es un hecho
        # observado y no una intencion declarada.
        obs = _cuota_observada()
        if obs is not None:
            share = obs
            fuente_cuota = "observed"

        return {
            "ok": True,
            "share_source": fuente_cuota,
            "node": node,
            "node_subversion": rpc.get_network_info().get("subversion"),
            "via": transport_of(_active_url(node)),
            "chain": info.get("chain"),
            "tip": data["tip"],
            "period": {
                "index": data["period_start"] // signaling.BIP110["period"],
                "start": data["period_start"],
                "end": data["period_end"],
                "scanned": data["blocks_scanned"],
                "remaining": data["blocks_remaining"],
            },
            "signalling_blocks": data["signalling"],
            "threshold_blocks": data["threshold"],
            "threshold_pct": data["threshold_pct"],
            "pct_of_scanned": data["pct_of_scanned"],
            "pct_of_period": data["pct_of_period"],
            "threshold_reachable": data["threshold_reachable"],
            "max_possible": data["max_possible"],
            "signalling_by_pool": by_pool,
            "milestones": signaling.milestones(data["tip"]),
            "minority_chain": signaling.minority_chain(share),
            # Cuando llegarian esos mismos hitos si la cadena BIP-110 se
            # separa. Van juntos a proposito: son la misma altura contada
            # en dos cadenas distintas, y esa es toda la historia.
            "milestone_projection": signaling.milestone_projection(share),
            "updated": int(time.time()),
        }
    except Exception as e:
        _invalidate_pick(node)
        return {"ok": False, "node": node, "error": _explicar(e), "motivo": _motivo(e), "detalle": _detalle(e),
                "hint": "Revisa BTC_RPC_URL / BTC_RPC_TOR_URL, usuario y clave."}


@app.route("/api/miners")
def miners():
    node = _pick_node()
    # Tambien en segundo plano: escanea hasta 2016 cabeceras, que por Tor
    # son decenas de idas y vueltas. Ningun endpoint del panel se calcula
    # ya dentro de la peticion.
    return jsonify(_cached_bg("miners", lambda: _build_miners(node), node))


def _build_pools(node=DEFAULT_NODE):
    try:
        rpc = _rpc(node)
        return dict(ok=True, node=node, via=transport_of(_active_url(node)),
                    **poolsmod.hashrate_share(
                        rpc, sample=POOLS_SAMPLE, signals_fn=signaling.signals_bit))
    except Exception as e:
        _invalidate_pick(node)
        return {"ok": False, "node": node, "error": _explicar(e), "motivo": _motivo(e), "detalle": _detalle(e)}


@app.route("/api/pools")
def pools_endpoint():
    node = _pick_node()
    return jsonify(_cached_bg("pools", lambda: _build_pools(node), node))


@app.route("/api/simulate")
def simulate():
    """Viabilidad de la cadena minoritaria para una cuota arbitraria."""
    try:
        share = float(request.args.get("share", "0.02"))
    except ValueError:
        share = 0.02
    share = max(0.0, min(1.0, share))
    return jsonify(signaling.minority_chain(share))


def _split_addr(addr):
    """
    Separa 'host:puerto' admitiendo IPv6 en la forma [::1]:8333.
    Contar los dos puntos no vale: rompe con IPv6.
    """
    if addr.startswith("["):
        host, _, port = addr.partition("]")
        return host[1:], port.lstrip(":")
    host, sep, port = addr.rpartition(":")
    return (host, port) if sep else (addr, "")


def _seed_addresses(rpc, include_onion):
    """
    Semillas del nodo propio, de DOS fuentes que no son la misma cosa.

    Filtramos por el campo 'network' que ya da Bitcoin Core, no por la forma
    del texto. Descartamos not_publicly_routable (incluye la conexion local
    del propio panel) e i2p, que no es alcanzable sin un router I2P.

    1. getpeerinfo: con quien habla el nodo AHORA. Es lo que habia, y con un
       nodo con onlynet restringido se queda en nada: la mayoria de sus
       peers son de redes no sondeables y quedan tres o cuatro utiles. Con
       tan pocas, una que no conteste deja el sondeo en CERO. Depender de
       una foto instantanea de los peers es un punto unico de fallo.

    2. getnodeaddresses: a quien CONOCE el nodo. Cientos de direcciones,
       muchas IPv4 que el VPS alcanza en claro y rapido. Sigue siendo dato
       del nodo propio: no entra ningun tercero.

    El ORDEN importa, porque luego se recorta a CRAWL_MAX_SEEDS:

      1. peers conectados, que estan vivos ahora mismo
      2. libreta de ipv4 e ipv6, que el VPS alcanza en claro y rapido
      3. libreta general, que con onlynet=onion es casi toda onion

    Sin el paso 2 el recorte se llevaba 60 semillas onion de 60, y cada una
    habia que sondearla por Tor. Funcionaba, pero pagaba un circuito por
    semilla para llegar al mismo sitio: el primer getaddr devuelve IPv4 de
    todas formas. Se pide la libreta por red a proposito (el argumento
    existe desde Core v22) en vez de filtrar despues, porque filtrar
    despues no sirve de nada si en las 500 que devuelve no viene ninguna.
    """
    wanted = {"ipv4", "ipv6"}
    if include_onion:
        wanted.add("onion")

    seeds, skipped, seen = [], {}, set()

    def add(net, host, port):
        if net not in wanted or not host or not port:
            skipped[net or "desconocida"] = skipped.get(net or "desconocida", 0) + 1
            return
        a = (host, int(port))
        if a not in seen:
            seen.add(a)
            seeds.append(a)

    for p in rpc.get_peer_info():
        host, port = _split_addr(p.get("addr", ""))
        add(p.get("network") or "", host, port if port.isdigit() else "")

    # La libreta es un extra: si el nodo es viejo o la llamada falla, nos
    # quedamos con los peers en vez de tumbar el sondeo entero.
    cuantas = int(os.environ.get("CRAWL_ADDRMAN", "500"))
    aviso = None
    for red in ("ipv4", "ipv6", None):
        try:
            libreta = rpc.get_node_addresses(cuantas, red)
        except Exception as e:
            # Un fallo pidiendo una red concreta no debe impedir las demas;
            # solo se avisa del primero, que es el que explica el resto.
            aviso = aviso or _explicar(e)[:120]
            continue
        for a in libreta:
            add(a.get("network") or "", a.get("address") or "", a.get("port") or 0)

    # 'skipped' solo lleva enteros: el que llama los suma entre nodos y un
    # texto ahi dentro reventaria la suma. El motivo va por su propio canal.
    return seeds, skipped, aviso


def _repartir_semillas(seeds, max_seeds, onion_min):
    """
    Recorta a max_seeds sin que un solo nodo se lleve el cupo entero.

    Recortar con `seeds[:max_seeds]`, o sea por orden de nodo, sale mal en
    cuanto los dos nodos tienen redes distintas: un nodo con onlynet
    restringido devuelve una libreta sin ninguna IPv4, porque Bitcoin Core
    no guarda direcciones de redes que no puede alcanzar, y si va primero
    ocupa todas las plazas con onion antes de mirar las del otro.

    Ahora manda la red, no el nodo. Primero clearnet, que el VPS alcanza
    directo y en milisegundos; y se reservan onion_min plazas para onion,
    porque son la unica via a esa parte de la red y salen gratis (Tor ya
    esta levantado para el RPC). Si de una red no hay bastantes, la otra
    ocupa el hueco: nunca se devuelven menos semillas de las que hay.
    """
    clear = [a for a in seeds if crawlermod.network_of(a[0]) in ("ipv4", "ipv6")]
    onion = [a for a in seeds if crawlermod.network_of(a[0]) == "onion"]
    cupo_onion = min(onion_min, len(onion), max_seeds)
    out = clear[:max_seeds - cupo_onion] + onion[:cupo_onion]
    if len(out) < max_seeds:  # sobran plazas: las rellena quien pueda
        resto = [a for a in clear + onion if a not in out]
        out += resto[:max_seeds - len(out)]
    return out


def _por_red(addrs):
    """Cuantas direcciones hay de cada red. Para diagnostico, no para la UI."""
    d = {}
    for host, _port in addrs:
        n = crawlermod.network_of(host)
        d[n] = d.get(n, 0) + 1
    return d


_tor_probe = {"at": 0, "ok": False}


def _tor_socks_open(host, port, ttl=60):
    """
    ¿Hay un SOCKS de Tor escuchando de verdad?

    Se comprueba abriendo el puerto, no deduciendolo de la configuracion.
    Un nodo en onlynet=onion no aporta ni una semilla clearnet, asi que si
    ademas descartamos las .onion por no tener CRAWL_VIA_TOR=true el sondeo
    se queda sin nada que hacer aunque Tor este ahi delante.
    """
    now = time.time()
    if now - _tor_probe["at"] < ttl:
        return _tor_probe["ok"]
    import socket as _s
    sock = _s.socket()
    sock.settimeout(2)
    try:
        ok = sock.connect_ex((host, port)) == 0
    except OSError:
        ok = False
    finally:
        try:
            sock.close()
        except OSError:
            pass
    _tor_probe.update(at=now, ok=ok)
    return ok


def _build_nodes():
    use_tor = os.environ.get("CRAWL_VIA_TOR", "false").lower() == "true"
    max_nodes = int(os.environ.get("CRAWL_MAX_NODES", "250"))
    max_seeds = int(os.environ.get("CRAWL_MAX_SEEDS", "60"))
    tor_host = os.environ.get("TOR_HOST", "127.0.0.1")
    tor_port = int(os.environ.get("TOR_PORT", "9050"))

    # Solo tiene sentido sondear .onion si hay un SOCKS de Tor a mano.
    rpc = _rpc()
    tor_available = use_tor or rpc.is_onion or _tor_socks_open(tor_host, tor_port)
    include_onion = tor_available and os.environ.get(
        "CRAWL_INCLUDE_ONION", "true").lower() == "true"

    # Por Tor cada handshake tarda segundos: menos hilos y mas margen.
    threads = int(os.environ.get("CRAWL_THREADS", "6" if use_tor else "16"))
    timeout = int(os.environ.get("CRAWL_TIMEOUT", "20" if use_tor else "8"))
    budget = int(os.environ.get("CRAWL_BUDGET", "600" if tor_available else "180"))

    # Semillas de TODOS los nodos configurados, no solo del canonico.
    # Los dos nodos pueden tener configuraciones de red distintas: uno en
    # onlynet=onion no aporta ni una semilla clearnet, y descartarlo entero
    # deja el sondeo sin arrancar. Sumarlos no mezcla datos de terceros,
    # siguen siendo nodos propios.
    seeds, skipped, errors, per_node = [], {}, {}, {}
    seen = set()
    for name in NODE_NAMES:
        if not _node_configured(name):
            continue
        try:
            s, sk, aviso = _seed_addresses(_rpc(name), include_onion)
        except Exception as e:
            errors[name] = _explicar(e)
            continue
        if aviso:
            errors[name + ":getnodeaddresses"] = aviso
        nuevas = 0
        for a in s:
            if a not in seen:
                seen.add(a)
                seeds.append(a)
                nuevas += 1
        per_node[name] = {"aportadas": nuevas, "total": len(s)}
        for k, v in sk.items():
            skipped[k] = skipped.get(k, 0) + v

    if not seeds:
        if errors and not per_node:
            # No tragarse el motivo: casi siempre es que el RPC no conecta,
            # y confundirlo con "el crawler no encuentra nodos" cuesta una tarde.
            return {"ok": False,
                    "error": "No se pudo leer getpeerinfo de ningun nodo.",
                    "por_nodo": errors,
                    "hint": "Comprueba /api/health. Si usas .onion, que Tor este arriba."}
        hint = ("Los nodos no tienen peers IPv4 ni IPv6 (probablemente "
                "onlynet=onion). Para sondear hace falta Tor: arranca uno o "
                "pon CRAWL_VIA_TOR=true.") if not tor_available else (
                "Los nodos no tienen ningun peer sondeable ahora mismo.")
        return {"ok": False,
                "error": "Sin semillas sondeables entre los peers de los nodos.",
                "peers_descartados_por_red": skipped,
                "por_nodo": errors or per_node,
                "tor_disponible": tor_available,
                "hint": hint}

    seeds = _repartir_semillas(seeds, max_seeds,
                               int(os.environ.get("CRAWL_SEEDS_ONION", "10")))
    results = crawlermod.crawl(
        seeds, max_nodes=max_nodes, threads=threads, timeout=timeout,
        use_tor=use_tor, include_onion=include_onion, budget_seconds=budget,
        tor_host=tor_host, tor_port=tor_port)

    probed = ["ipv4", "ipv6"] + (["onion"] if include_onion else [])
    summary = crawlermod.summarise(
        results, networks_probed=probed,
        networks_skipped=["i2p", "cjdns"] + ([] if include_onion else ["onion"]))
    # Los diagnosticos van SIEMPRE, no solo cuando no hay ni una semilla.
    #
    # Estuvieron solo en el camino de fallo total y por eso un fallo parcial
    # pasa desapercibido: si getpeerinfo falla en un nodo y el otro aporta
    # una sola semilla, la respuesta sale con ok:true sin rastro ni de la
    # excepcion ni de los peers descartados. Un fallo parcial es justo el
    # que necesita el diagnostico, porque no se nota mirando.
    summary.update(ok=True, seeds_used=len(seeds), via_tor=use_tor,
                   seeds_por_nodo=per_node, updated=int(time.time()),
                   errores_por_nodo=errors,
                   peers_descartados_por_red=skipped,
                   semillas_por_red=_por_red(seeds),
                   tor_disponible=tor_available,
                   presupuesto_s=budget)
    return summary


@app.route("/api/nodes")
def nodes():
    return jsonify(_cached_bg("nodes", _build_nodes))


_PERIODS_FILE = os.path.join(CACHE_DIR, "periods.json") if CACHE_DIR else None
HISTORY_PERIODS = int(os.environ.get("HISTORY_PERIODS", "5"))


def _load_periods():
    if not _PERIODS_FILE or not os.path.exists(_PERIODS_FILE):
        return {}
    try:
        with open(_PERIODS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_periods(data):
    if not _PERIODS_FILE:
        return
    try:
        tmp = _PERIODS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, _PERIODS_FILE)
    except OSError:
        pass


def _period_stats(rpc, index):
    """
    Señalizacion de un periodo de retarget CERRADO, con atribucion a pool.

    Se cachea en disco para siempre: un periodo cerrado es inmutable, asi
    que recalcularlo es tirar tiempo, y por Tor mucho tiempo.

    Solo se piden las coinbase de los bloques que señalizan, no las de los
    2016. Son unas decenas en vez de dos mil, y el resto de la informacion
    esta en las cabeceras, que son baratas.
    """
    p = signaling.BIP110["period"]
    start, end = index * p, index * p + p - 1
    headers = rpc.headers_for_range(start, end)
    sig = [h for h in headers if signaling.signals_bit(h["version"])]

    by_pool = {}
    if sig:
        for a in poolsmod.attribute_blocks(rpc, sig):
            by_pool[a["pool"]] = by_pool.get(a["pool"], 0) + 1

    return {
        "period": index,
        "start": start,
        "end": end,
        "blocks": len(headers),
        "signalling": len(sig),
        "pct": round(len(sig) / p * 100, 4),
        "by_pool": by_pool,
    }


def _build_history(node=DEFAULT_NODE, periods=HISTORY_PERIODS):
    """Los ultimos `periods` periodos de retarget CERRADOS."""
    try:
        rpc = _rpc(node)
        tip = rpc.get_block_count()
        current = tip // signaling.BIP110["period"]
        cache = _load_periods()
        wanted = [current - n for n in range(periods, 0, -1)]

        out, dirty = [], False
        for idx in wanted:
            if idx < 0:
                continue
            key = f"{node}:{idx}"
            if key not in cache:
                cache[key] = _period_stats(rpc, idx)
                dirty = True
            out.append(cache[key])
        if dirty:
            _save_periods(cache)

        total_blocks = sum(p["blocks"] for p in out)
        total_sig = sum(p["signalling"] for p in out)
        agg = {}
        for p in out:
            for k, v in p["by_pool"].items():
                agg[k] = agg.get(k, 0) + v
        top = max(agg.items(), key=lambda kv: kv[1]) if agg else None

        return {
            "ok": True,
            "node": node,
            "periods": out,
            "total_blocks": total_blocks,
            "signalling_blocks": total_sig,
            "signalling_pct": round(total_sig / total_blocks * 100, 4) if total_blocks else 0.0,
            "by_pool": agg,
            "top_pool": top[0] if top else None,
            "top_pool_blocks": top[1] if top else 0,
            "other_pools": max(0, len(agg) - 1),
            "updated": int(time.time()),
        }
    except Exception as e:
        _invalidate_pick(node)
        return {"ok": False, "node": node, "error": _explicar(e), "motivo": _motivo(e), "detalle": _detalle(e)}


@app.route("/api/history")
def history():
    node = _pick_node()
    try:
        n = max(1, min(20, int(request.args.get("periods", HISTORY_PERIODS))))
    except ValueError:
        n = HISTORY_PERIODS
    return jsonify(_cached_bg("history", lambda: _build_history(node, n), f"{node}:{n}"))


def _fork_height(rpc_a, rpc_b, lo, hi):
    """
    Ultima altura en la que los dos nodos coinciden, por busqueda binaria.
    Presupone que en `lo` coinciden y en `hi` no. Son unas 20 llamadas por
    nodo, asi que es barato incluso por Tor.
    """
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if rpc_a.call("getblockhash", mid) == rpc_b.call("getblockhash", mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


_STATE_FILE = os.path.join(CACHE_DIR, "chain_state.json") if CACHE_DIR else None


def _load_state():
    """
    Alturas de separacion y reunificacion, en disco.

    Tienen que sobrevivir a los reinicios: una vez que las cadenas se
    separan, la altura de separacion es un hecho historico y borrarla seria
    reescribir lo que paso. La cache en memoria no vale para esto.
    """
    if not _STATE_FILE or not os.path.exists(_STATE_FILE):
        return {}
    try:
        with open(_STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_state(state):
    if not _STATE_FILE:
        return
    try:
        tmp = _STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, _STATE_FILE)   # atomico: no deja el fichero a medias
    except OSError:
        pass


# A partir de cuantos bloques de diferencia entre los dos nodos deja de ser
# ruido de propagacion y pasa a ser algo que contar. Uno o dos de hueco es
# normal y pasa varias veces al dia; tres seguidos, ya no.
STALL_GAP = 3

# Y un hueco pequeño que NO se mueve tambien cuenta.
#
# El 2026-08-08, con la altura obligatoria recien alcanzada, el nodo BIP-110
# se quedo congelado con un solo bloque de diferencia. Mirando solo el tamaño
# del hueco, el panel habria dicho "coinciden" durante la media hora larga
# que tardo el segundo bloque en aparecer, que es justo el rato que habia que
# contar. Lo que distingue propagacion de paron no es cuanto se separan, es
# cuanto tiempo llevan separados.
STALL_SECONDS = 1800


def _tip_time(rpc, tip):
    """Hora del bloque en la punta, o None. Dos llamadas."""
    try:
        return rpc.call("getblockheader", rpc.call("getblockhash", tip))["time"]
    except Exception:
        return None


def _pace(rpc, tip, window=144, suelo=None):
    """
    Segundos por bloque en los ultimos `window` bloques, y hora del ultimo.
    Dos llamadas, no `window`: solo hacen falta las marcas de tiempo de los
    dos extremos.

    OJO CON `suelo`, que aqui no es un detalle. Sin el, la ventana de 144
    bloques se sale hacia atras de la rama: el dia de la separacion la rama
    minoritaria tiene tres o cuatro bloques propios, y los otros 140 serian
    bloques ANTERIORES a la bifurcacion, comunes a las dos cadenas y minados
    a diez minutos. Se estaria midiendo el ritmo de la cadena mayoritaria y
    enseñandolo como el de la minoritaria, o sea la rama pareceria sana
    durante semanas justo cuando lo que importa es ver que no lo esta.

    Con `suelo` puesto en la altura de bifurcacion, el intervalo sale de
    bloques que son solo de esa rama, y si todavia no hay ninguno, se dice
    que no se puede medir en vez de inventar un numero.

    Devuelve (segundos por bloque, hora del ultimo, bloques medidos). El
    tercero no sobra: recien separadas las cadenas la media sale de uno o dos
    intervalos, y un numero con esa base no se puede enseñar igual que uno
    sacado de 144. La interfaz dice sobre cuantos bloques va.
    """
    lo = max(0, tip - window)
    if suelo is not None:
        lo = max(lo, suelo)
    try:
        t_hi = rpc.call("getblockheader", rpc.call("getblockhash", tip))["time"]
    except Exception:
        return None, None, 0
    if lo >= tip:
        # Ningun bloque propio todavia. La hora del ultimo si vale, y es
        # justo la que dice si la rama esta parada.
        return None, t_hi, 0
    try:
        t_lo = rpc.call("getblockheader", rpc.call("getblockhash", lo))["time"]
    except Exception:
        return None, t_hi, 0
    span = t_hi - t_lo
    n = tip - lo
    return (round(span / n, 1) if span > 0 else None), t_hi, n


def _build_chains():
    """
    Estado de las dos cadenas. Dato verificable: o los dos nodos tienen el
    mismo hash a la misma altura o no lo tienen.

    Tres estados, y los decide el backend, nunca el usuario:
      pre_split   los dos nodos coinciden
      split       han divergido
      reunified   vuelven a coincidir tras haber divergido

    Mayoritaria y minoritaria se deciden por TRABAJO ACUMULADO, no por
    reglas ni por preferencia. La cadena con mas chainwork es la mayoritaria
    aunque sea la que aplica BIP-110.
    """
    saved = _load_state()
    out = {
        "ok": True,
        "state": "pre_split",
        "split_height": saved.get("split_height"),
        "split_hashes": saved.get("split_hashes"),
        "reunified_height": saved.get("reunified_height"),
        "nodes": {},
        "degraded": False,
        "updated": int(time.time()),
    }

    # Los dos nodos a la vez, y las dos consultas de cada uno en un solo
    # batch. En serie eran cuatro idas y vueltas por Tor solo para esto, y
    # por Tor cada una son segundos.
    rpcs, info, crudo = {}, {}, {}

    def leer(name):
        try:
            r = _rpc(name)
            bi, ni = r.batch([("getblockchaininfo", []), ("getnetworkinfo", [])])
            crudo[name] = (r, bi, ni)
        except Exception as e:
            _invalidate_pick(name)
            crudo[name] = e

    hilos = []
    for name in NODE_NAMES:
        if not _node_configured(name):
            out["nodes"][name] = {"ok": False, "error": "no configurado"}
            continue
        t = threading.Thread(target=leer, args=(name,))
        t.start()
        hilos.append(t)
    for t in hilos:
        t.join(timeout=CHAIN_TIMEOUT)

    for name in NODE_NAMES:
        if not _node_configured(name):
            continue
        if name not in crudo:
            # El hilo no termino a tiempo. Sin esto el nodo se quedaba sin
            # entrada y el propio manejo del fallo reventaba mas abajo
            # buscandola, soltando un KeyError crudo a la pantalla.
            out["nodes"][name] = {
                "ok": False,
                "error": f"el nodo no respondio en {CHAIN_TIMEOUT}s"}
            continue
        got = crudo[name]
        if isinstance(got, Exception):
            out["nodes"][name] = {"ok": False, "error": str(got)}
            continue
        try:
            r, bi, ni = got
            rpcs[name] = r
            info[name] = bi
            out["nodes"][name] = {
                "ok": True,
                "subversion": ni.get("subversion"),
                "tip": bi.get("blocks"),
                "hash": bi.get("bestblockhash"),
                "chainwork": bi.get("chainwork"),
                "via": transport_of(_active_url(name)),
                "enforces": "REDUCED_DATA" in " ".join(
                    ni.get("localservicesnames") or []),
            }
        except Exception as e:
            _invalidate_pick(name)
            out["nodes"][name] = {"ok": False, "error": _explicar(e), "motivo": _motivo(e), "detalle": _detalle(e)}

    if len(rpcs) < 2:
        # "No configurado" y "no responde" son cosas distintas y no pueden
        # dar el mismo aviso. Lo primero es una decision de despliegue; lo
        # segundo, una averia. Confundirlas asusta sin motivo.
        faltan = [n for n in NODE_NAMES if not out["nodes"].get(n, {}).get("ok")]
        sin_configurar = [n for n in faltan if not _node_configured(n)]
        out["state"] = saved.get("state", "pre_split")
        out["single_node"] = bool(sin_configurar) and len(sin_configurar) == len(faltan)
        out["degraded"] = not out["single_node"]
        out["missing"] = faltan
        out["note"] = ("Solo hay un nodo configurado, no se compara nada."
                       if out["single_node"] else
                       "Falta un nodo, no se puede comparar. Esto NO significa "
                       "que las cadenas se hayan separado.")
        return out

    a, b = rpcs["core"], rpcs["knots"]
    ha, hb = out["nodes"]["core"]["tip"], out["nodes"]["knots"]["tip"]
    common = min(ha, hb)

    try:
        same = a.call("getblockhash", common) == b.call("getblockhash", common)
    except Exception as e:
        out["degraded"] = True
        out["error"] = _explicar(e)
        out["motivo"] = _motivo(e)
        out["detalle"] = _detalle(e)
        return out

    if same:
        out["state"] = "reunified" if saved.get("split_height") else "pre_split"
        out["common_height"] = common
        out["height_gap"] = abs(ha - hb)

        # UN NODO PARADO NO ES UNA SEPARACION, Y AQUI ESTA EL HUECO.
        #
        # A partir de la altura obligatoria, un nodo BIP-110 solo acepta
        # bloques que señalicen Y cuyos antepasados desde esa altura tambien
        # señalicen. Con una señalizacion baja, lo primero que hace no es
        # bifurcarse: es quedarse quieto, porque no hay ningun bloque valido
        # para el. Su tip se congela mientras el otro avanza.
        #
        # El hash a la altura comun sigue coincidiendo, asi que `same` es
        # True y el estado es correcto: no hay separacion. Pero decir solo
        # "las dos cadenas coinciden" con un nodo congelado desde hace horas
        # es verdad y engaña, que es peor que equivocarse. La distancia se
        # mide y se dice.
        if out["height_gap"] >= 1:
            atras = "core" if ha < hb else "knots"
            # Solo se le pregunta al nodo rezagado, nunca a los dos.
            t = _tip_time(rpcs[atras], out["nodes"][atras]["tip"])
            quieto = False
            if t:
                out["nodes"][atras]["last_block_time"] = t
                parado = int(time.time()) - t
                out["nodes"][atras]["seconds_since_last_block"] = parado
                quieto = parado >= STALL_SECONDS
            # Por tamaño o por tiempo. Cualquiera de los dos basta: un hueco
            # grande es raro aunque sea reciente, y un hueco de un bloque que
            # lleva media hora sin moverse no es propagacion.
            if out["height_gap"] >= STALL_GAP or quieto:
                out["lagging"] = atras
        if out["state"] == "reunified" and not saved.get("reunified_height"):
            saved["reunified_height"] = common
            saved["state"] = "reunified"
            _save_state(saved)
            out["reunified_height"] = common
    else:
        out["state"] = "split"
        if not saved.get("split_height"):
            fork = _fork_height(a, b, 0, common)
            saved["split_height"] = fork
            saved["split_hashes"] = {
                "core": a.call("getblockhash", fork + 1),
                "knots": b.call("getblockhash", fork + 1),
            }
            saved["state"] = "split"
            saved.pop("reunified_height", None)
            _save_state(saved)
            out["split_height"] = fork
            out["split_hashes"] = saved["split_hashes"]
            out["reunified_height"] = None

    # CUANDO se abrio la separacion, no solo a que altura.
    #
    # "Se abrio en el bloque 961.631" no le dice nada a quien no cuenta el
    # tiempo en bloques, y esa es casi toda la gente que entra. La hora sale
    # de la cabecera del primer bloque divergente, se guarda una vez y no se
    # vuelve a pedir: es un hecho historico y no cambia.
    if out["state"] == "split":
        if not saved.get("split_time"):
            h = (saved.get("split_hashes") or {}).get("core")
            if h:
                try:
                    saved["split_time"] = a.call("getblockheader", h)["time"]
                    _save_state(saved)
                except Exception:                            # noqa: BLE001
                    pass
        if saved.get("split_time"):
            out["split_time"] = saved["split_time"]
            out["split_seconds_ago"] = int(time.time()) - saved["split_time"]

    # Mayoritaria y minoritaria por trabajo acumulado, no por reglas.
    work = {n: int(out["nodes"][n].get("chainwork") or "0", 16) for n in rpcs}
    maj_node = max(work, key=work.get)
    min_node = "knots" if maj_node == "core" else "core"

    def side(name):
        tip = out["nodes"][name]["tip"]
        ritmo, ultima, medidos = None, None, 0
        if out["state"] == "split":
            # Cuatro viajes mas por Tor. Solo se enseña en la vista de dos
            # cadenas, asi que antes de la separacion no se calcula.
            ritmo, ultima, medidos = _pace(rpcs[name], tip,
                                           suelo=out.get("split_height"))
        return {
            "node": name,
            "tip": tip,
            "hash": out["nodes"][name]["hash"],
            "enforces": out["nodes"][name]["enforces"],
            "avg_interval_sec": ritmo,
            "interval_blocks": medidos,
            # Cuanto hace del ultimo bloque. Es lo que separa "va despacio"
            # de "esta parada", y el intervalo medio no lo dice: una rama que
            # dejo de producir hace un mes conserva la media que tenia.
            "last_block_time": ultima,
            "seconds_since_last_block": (int(time.time()) - ultima) if ultima else None,
            "blocks_since_split": (tip - out["split_height"]
                                   if out["split_height"] is not None else None),
        }

    out["majority"] = side(maj_node)
    out["minority"] = side(min_node)
    out["same_chain"] = (out["state"] != "split")
    if out["same_chain"]:
        out["note"] = ("Los dos nodos siguen la misma cadena. Mayoritaria y "
                       "minoritaria son la misma hasta que se separen.")
    else:
        out["note"] = ("Las cadenas se han separado. Cada cifra vale solo para "
                       "su cadena, y no se suman.")
    return out


@app.route("/api/chain")
def chain():
    # En segundo plano como los demas: son varias idas y vueltas por Tor y
    # se ha visto pasar de los 100 segundos que aguanta el CDN, que corta
    # con un 524 y una pagina de error que el navegador no sabe leer.
    return jsonify(_cached_bg("chains", _build_chains))


@app.route("/api/health")
def health():
    """
    Estado de los dos nodos, y por que direccion esta hablando con cada uno.

    Lo del transporte no es un detalle: con respaldo configurado el panel
    puede estar leyendo por Tor sin que nadie se entere, y un panel cuya
    tesis es saber de donde sale cada cifra no puede cambiar de ruta a
    escondidas.
    """
    out, code = {"nodes": {}, "warnings": []}, 200
    tope = _health_timeout()

    def mirar(name):
        """Estado de un nodo. Se llama a los dos EN PARALELO: por Tor cada
        uno tarda segundos y hacerlo en serie sumaba mas de veinte, con lo
        que el propio healthcheck de Docker daba por muerto un contenedor
        perfectamente vivo.

        Se reintenta mientras quede plazo, y no por gusto: un servicio
        oculto falla de vez en cuando y se recupera solo. Al recargar Tor
        en el nodo, el servicio republica su descriptor con puntos de
        introduccion nuevos y los clientes que tienen el viejo en cache
        fallan hasta que lo vuelven a pedir, y luego vuelve solo sin que
        nadie toque nada. Esos fallos ademas suelen ser RAPIDOS (el SOCKS
        contesta 0x06 en un segundo), asi que casi siempre sobra plazo
        para otro intento: sin reintento se reporta caido un nodo que
        habria respondido a la segunda.
        """
        urls = _node_urls(name)
        if not urls:
            return {"ok": False, "error": "no configurado"}
        entry = {"configured": [{"url": u, "via": transport_of(u)} for u in urls]}
        limite = time.time() + tope
        intento = 0
        while True:
            intento += 1
            try:
                rpc = _rpc(name)
                # Las dos consultas en un solo batch: por Tor cada ida y
                # vuelta son varios segundos, y pedirlas por separado
                # duplica la espera sin ganar nada.
                info, ni = rpc.batch([("getblockchaininfo", []),
                                      ("getnetworkinfo", [])])
                active = _active_url(name)
                entry.update(ok=True, chain=info.get("chain"),
                             blocks=info.get("blocks"),
                             subversion=ni.get("subversion"),
                             active_url=active, via=transport_of(active),
                             enforces_bip110="REDUCED_DATA" in " ".join(
                                 ni.get("localservicesnames") or []))
                if intento > 1:
                    entry["intentos"] = intento
                if len(urls) > 1 and transport_of(active) == "tor":
                    entry["nota"] = ("respondiendo por Tor: la direccion "
                                     "clearnet no contesta")
                return entry
            except Exception as e:
                _invalidate_pick(name)
                # Solo se reintenta si queda plazo de sobra: agotarlo aqui
                # haria que el hilo llegue tarde al join y el nodo saldria
                # como "sin respuesta", que es peor que el error de verdad.
                if intento < HEALTH_INTENTOS and time.time() < limite - 8:
                    time.sleep(1)
                    continue
                entry.update(ok=False, error=_explicar(e), motivo=_motivo(e), detalle=_detalle(e),
                             intentos=intento)
                return entry

    hilos, res = [], {}
    for name in NODE_NAMES:
        t = threading.Thread(target=lambda n=name: res.__setitem__(n, mirar(n)))
        t.start()
        hilos.append(t)
    for t in hilos:
        t.join(timeout=tope)
    for name in NODE_NAMES:
        out["nodes"][name] = res.get(name, {
            "ok": False,
            "error": f"sin respuesta en {tope}s (el nodo va muy lento o no contesta)"})
    if not out["nodes"].get(DEFAULT_NODE, {}).get("ok"):
        code = 503

    # La comparacion de cadenas solo sirve si un nodo aplica BIP-110 y el
    # otro no. Con las dos direcciones apuntando al mismo nodo el panel
    # compararia un nodo consigo mismo y nunca veria una separacion, con
    # todo en verde. Es el fallo silencioso que hay que evitar.
    for name in NODE_NAMES:
        nota = out["nodes"].get(name, {}).get("nota")
        if nota:
            out["warnings"].append(f"El nodo '{name}' esta {nota}.")

    # Un nodo configurado que no responde tiene que decirse AQUI.
    #
    # Todas las comprobaciones de abajo exigen que el nodo conteste, asi
    # que con uno caido no salta ninguna y 'warnings' se queda vacio: el
    # panel se queda con un solo nodo sin decirlo en ningun sitio.
    # Quedarse tuerto es justo lo que no puede pasar en silencio, porque el
    # panel existe para comparar dos cadenas y con un nodo no compara nada.
    # "No configurado" no cuenta: eso es una decision de despliegue, no una
    # averia, y confundirlas alarma a quien arranca con un solo nodo.
    for name in NODE_NAMES:
        e = out["nodes"].get(name, {})
        if e.get("ok") or e.get("error") == "no configurado":
            continue
        out["warnings"].append(
            f"El nodo '{name}' esta configurado y NO responde, asi que el "
            "panel no puede comparar las dos cadenas y no detectaria una "
            f"separacion. Motivo: {e.get('error', 'desconocido')}")

    c, k = out["nodes"].get("core", {}), out["nodes"].get("knots", {})
    if c.get("ok") and c.get("enforces_bip110"):
        out["warnings"].append(
            "El nodo canonico aplica BIP-110. Tras el bloque 961.632 puede "
            "irse a la cadena minoritaria y el panel la contaria como si "
            "fuese la cadena. Pon aqui un nodo sin reduced_data.")
    if k.get("ok") and not k.get("enforces_bip110"):
        out["warnings"].append(
            "El nodo secundario NO aplica BIP-110, asi que la comparacion no "
            "puede detectar una separacion. Comprueba que no apunta al mismo "
            "nodo que el canonico.")
    if c.get("ok") and k.get("ok") and c.get("active_url") == k.get("active_url"):
        out["warnings"].append(
            "Los dos nodos estan usando la MISMA direccion. Se estaria "
            "comparando un nodo consigo mismo.")

    out["ok"] = out["nodes"].get(DEFAULT_NODE, {}).get("ok", False)

    # La direccion del RPC no sale de aqui. /api/health es publica, y una
    # direccion de servicio oculto es lo unico que impide que un
    # desconocido llame a la puerta del RPC e intente autenticarse todo el
    # dia sin coste.
    #
    # Lo que el panel necesita contar es por donde sale y si los dos nodos
    # son el mismo, no cual es. Las comparaciones de arriba ya se han hecho
    # con la direccion real; aqui solo queda la huella, que sirve para ver
    # de un vistazo si dos entradas coinciden o si una ha cambiado, y no se
    # deshace: son 56 caracteres base32 detras de un sha256.
    for entry in out["nodes"].values():
        if "active_url" in entry:
            entry["active_id"] = _huella(entry.pop("active_url"))
        if "configured" in entry:
            entry["configured"] = [{"via": c["via"], "id": _huella(c["url"])}
                                   for c in entry["configured"]]
    return jsonify(out), code


def _calentar():
    """
    Precalcula lo caro al arrancar. Sin esto, el primer visitante ve el
    aviso de "calculando" y tiene que volver. Va en un hilo aparte para no
    retrasar el arranque del servidor.
    """
    def correr():
        time.sleep(2)
        for nombre, ruta in (("chain", "/api/chain"), ("miners", "/api/miners"),
                             ("history", "/api/history"), ("pools", "/api/pools"),
                             ("nodes", "/api/nodes")):
            try:
                app.test_client().get(ruta)
            except Exception:
                pass
    threading.Thread(target=correr, daemon=True).start()


if os.environ.get("WARM_ON_START", "true").lower() == "true":
    _calentar()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8110")))
