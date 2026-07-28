"""
Atribucion de bloques a pools leyendo la coinbase.

AVISO IMPORTANTE sobre la fiabilidad de esto:
la etiqueta de la coinbase es texto que el pool escribe voluntariamente.
No esta autenticada. Un pool puede omitirla, cambiarla o imitar la de otro.
La atribucion es por tanto una convencion util, no una prueba.
"""

import os
import re

# Etiquetas que los pools escriben en el scriptSig de la coinbase.
#
# Se comparan como subcadena literal y sin distinguir mayusculas. Ojo con
# dos cosas que estropearon la version anterior:
#
#   - No exigir barra delante. La barra es una convencion, no una regla.
#     Luxor escribe "Powered by Luxor Tech", MARA escribe "| MARA Made in
#     USA |" y SpiderPool pone la barra detras ("SpiderPool/323/"). Pedir
#     "/Luxor" o "/MARA" dejaba fuera a esos pools enteros.
#   - No usar regex aqui. "/BTC.com" como patron hace que el punto sea un
#     comodin y case cualquier "/BTCxcom".
#
# Verificado contra 1000 bloques del nodo propio (958849-959848).
POOL_TAGS = [
    (b"Foundry USA Pool", "Foundry USA"),
    (b"Foundry", "Foundry USA"),
    (b"AntPool", "AntPool"),
    (b"ViaBTC", "ViaBTC"),
    (b"F2Pool", "F2Pool"),
    (b"\xe4\xba\x94\xe6\x96\xb9", "F2Pool"),
    (b"SpiderPool", "SpiderPool"),
    (b"BTC.com", "BTC.com"),
    (b"btccom", "BTC.com"),
    (b"Binance", "Binance Pool"),
    (b"Luxor", "Luxor"),
    (b"MARA Made in USA", "MARA Pool"),
    (b"MARAPool", "MARA Pool"),
    (b"/MARA", "MARA Pool"),
    (b"SBICrypto", "SBI Crypto"),
    (b"SBI Crypto", "SBI Crypto"),
    (b"Braiins", "Braiins Pool"),
    (b"/slush", "Braiins Pool"),
    (b"OCEAN.XYZ", "Ocean"),
    (b"/OCEAN", "Ocean"),
    (b"SecPool", "SecPool"),
    (b"WhitePool", "WhitePool"),
    (b"trustpool", "Trustpool"),
    (b"Poolin", "Poolin"),
    (b"BTCPool", "BTC Pool"),
    (b"Carbon", "Carbon Negative"),
    (b"Ultimus", "UltimusPool"),
    (b"BitFuFu", "BitFuFu"),
    (b"TerraPool", "TerraPool"),
    (b"NiceHash", "NiceHash"),
    (b"Bitdeer", "Bitdeer"),
    (b"Rawpool", "Rawpool"),
    (b"PEGA", "PEGA Pool"),
    (b"1THash", "1THash"),
    (b"solo.ckpool.org", "Solo (ckpool)"),
    (b"ckpool", "ckpool"),
    (b"Mining-Dutch", "Mining-Dutch"),
    (b"Innopolis", "Innopolis Tech"),
    (b"RedRock Pool", "RedRock"),
    (b"|parasite|", "Parasite"),
    (b"/DMND/", "DEMAND"),
    (b"p2p-spb.xyz", "p2p-spb"),
    (b"Public-Pool", "Public Pool"),
]

_POOL_TAGS_LOWER = [(p.lower(), name) for p, name in POOL_TAGS]


def identify(coinbase_hex):
    """
    Devuelve (nombre_pool, etiqueta_legible_de_la_coinbase).

    "Sin etiqueta" y "Desconocido" son cosas distintas y conviene no
    mezclarlas: la primera es un bloque cuya coinbase no lleva texto
    legible, la segunda una etiqueta que existe pero no sabemos de quien es.
    """
    try:
        raw = bytes.fromhex(coinbase_hex)
    except (ValueError, TypeError):
        return "Desconocido", ""

    low = raw.lower()
    for pattern, name in _POOL_TAGS_LOWER:
        if pattern in low:
            return name, _printable(raw)

    tag = _printable(raw)
    return ("Desconocido" if tag else "Sin etiqueta"), tag


def _printable(raw):
    """Extrae los trozos ASCII legibles de la coinbase, para inspeccion manual."""
    chunks = re.findall(rb"[\x20-\x7e]{4,}", raw)
    return " | ".join(c.decode("ascii", "ignore") for c in chunks)[:200]


def _default_chunk(rpc):
    """
    Bloques por peticion. Medido contra un nodo real: getblock verbosity=1
    de un bloque actual son unos 250 KB de JSON, casi todo la lista de
    txids. Con 120 bloques por lote son 30 MB, que por Tor se corta a media
    descarga. Por eso el lote va mucho mas corto cuando salimos por Tor.
    """
    env = os.environ.get("POOLS_CHUNK")
    if env and env.isdigit():
        return max(1, int(env))
    return 15 if getattr(rpc, "is_onion", False) else 60


def _coinbase_for_blocks(rpc, blockhashes, chunk=None):
    """
    Extrae la coinbase sin descargar bloques enteros.

    getblock verbosity=2 devolveria todas las transacciones enteras. En su
    lugar: verbosity=1, que solo trae los txids, y getrawtransaction del
    primero pasando el blockhash, lo que evita necesitar txindex.

    Ojo: verbosity=1 sigue sin ser barato. La lista de txids de un bloque
    lleno pesa del orden de 250 KB. Es mucho menos que verbosity=2, pero no
    es despreciable al multiplicarlo por el tamano de la muestra.
    """
    if chunk is None:
        chunk = _default_chunk(rpc)
    out = {}
    for i in range(0, len(blockhashes), chunk):
        batch = blockhashes[i:i + chunk]
        blocks = rpc.batch([("getblock", [bh, 1]) for bh in batch])
        first_txids = []
        valid = []
        for bh, blk in zip(batch, blocks):
            txs = blk.get("tx") or []
            if txs:
                first_txids.append(txs[0])
                valid.append(bh)
        if not first_txids:
            continue
        raws = rpc.batch([
            ("getrawtransaction", [txid, True, bh])
            for txid, bh in zip(first_txids, valid)
        ])
        for bh, raw in zip(valid, raws):
            try:
                out[bh] = raw["vin"][0]["coinbase"]
            except (KeyError, IndexError, TypeError):
                out[bh] = ""
    return out


def attribute_blocks(rpc, headers, chunk=None):
    """Atribuye pool a cada cabecera. headers: [{height, hash, version}]"""
    cb = _coinbase_for_blocks(rpc, [h["hash"] for h in headers], chunk=chunk)
    results = []
    for hdr in headers:
        pool, tag = identify(cb.get(hdr["hash"], ""))
        results.append({
            "height": hdr["height"],
            "version": hdr["version"],
            "pool": pool,
            "coinbase_tag": tag,
        })
    return results


def hashrate_share(rpc, sample=500, signals_fn=None):
    """
    Estima la cuota de hashrate de cada pool a partir de los ultimos
    `sample` bloques, medida contra el propio nodo (no contra un tercero).

    Devuelve tambien, por pool, cuantos de sus bloques señalizan, que es
    lo que permite construir la calculadora de coaliciones.
    """
    tip = rpc.get_block_count()
    start = max(0, tip - sample + 1)
    headers = rpc.headers_for_range(start, tip)
    attributed = attribute_blocks(rpc, headers)

    total = len(attributed)
    agg = {}
    for a in attributed:
        p = a["pool"]
        e = agg.setdefault(p, {"pool": p, "blocks": 0, "signalling": 0})
        e["blocks"] += 1
        if signals_fn and signals_fn(a["version"]):
            e["signalling"] += 1

    rows = []
    for e in agg.values():
        rows.append({
            "pool": e["pool"],
            "blocks": e["blocks"],
            "share_pct": round(e["blocks"] / total * 100, 2) if total else 0.0,
            "signalling_blocks": e["signalling"],
            "signals": e["signalling"] > 0,
            "signals_always": e["signalling"] == e["blocks"],
        })
    rows.sort(key=lambda r: -r["blocks"])

    # Cuantos pools se han sabido identificar y cuanto queda sin atribuir.
    # Va en la API para que la interfaz no tenga que escribirlo a mano y
    # quedarse obsoleta.
    sin_nombre = ("Desconocido", "Sin etiqueta")
    identified = [r for r in rows if r["pool"] not in sin_nombre]
    unattributed = sum(r["blocks"] for r in rows if r["pool"] in sin_nombre)

    return {
        "sample_blocks": total,
        "from_height": start,
        "to_height": tip,
        "pools_identified": len(identified),
        "unattributed_blocks": unattributed,
        "unattributed_pct": round(unattributed / total * 100, 2) if total else 0.0,
        "pools": rows,
        "caveat": ("Cuota estimada sobre una muestra de los ultimos bloques, "
                   "medida contra tu propio nodo. La etiqueta de la coinbase "
                   "no esta autenticada."),
    }
