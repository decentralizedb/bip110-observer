#!/usr/bin/env python3
"""
Auditoria de datos del panel.

Comprueba que TODA cifra que el panel enseña cuadra con el nodo y consigo
misma. La regla de esta auditoria:

    los numeros criticos se recalculan con codigo independiente, a partir
    del RPC crudo, sin reutilizar las funciones del panel.

Comprobar signals_bit() llamando a signals_bit() solo confirma el mismo
fallo dos veces. Aqui se reimplementa a proposito, y ademas se contrasta
con getdeploymentinfo, que es el contador de consenso del propio Bitcoin
Core: si el panel y la implementacion de referencia coinciden, la cifra es
solida sin depender de ningun tercero.

Uso:
    BTC_RPC_URL=... BTC_RPC_URL_KNOTS=... python3 audit.py
"""
import os
import sys
import time

import main
from rpc import BitcoinRPC

FALLOS, AVISOS = [], []


def fallo(msg):
    FALLOS.append(msg)
    print("  FALLO   " + msg)


def aviso(msg):
    AVISOS.append(msg)
    print("  AVISO   " + msg)


def ok(msg):
    print("  ok      " + msg)


def casi(a, b, tol=0.005):
    return a is not None and b is not None and abs(a - b) <= tol


def esperar(cli, ruta, limite=600):
    """
    Pide un endpoint hasta que deje de estar calculando.

    Los endpoints caros ya no se calculan dentro de la peticion: devuelven
    computing=True mientras trabajan por detras. La auditoria los daba por
    caidos, que es lo mismo que ocurriria a cualquier herramienta que
    hablara con esta API sin saberlo. Se espera, y si no llega a tiempo se
    dice cuanto se espero.
    """
    fin = time.time() + limite
    ultimo = None
    while time.time() < fin:
        ultimo = cli.get(ruta).get_json()
        if not (ultimo or {}).get("computing"):
            return ultimo
        time.sleep(5)
    return ultimo


# --------------------------------------------------------------------------
# Reimplementacion independiente. NO importar de signaling.py.
# --------------------------------------------------------------------------
def senaliza(version):
    """Version independiente: bits altos de versionbits + bit 4."""
    return (version & 0xE0000000) == 0x20000000 and bool(version & (1 << 4))


def contar_periodo(rpc, start, end):
    """Cuenta bloques que señalizan, pidiendo las cabeceras una a una."""
    n = 0
    total = 0
    for lo in range(start, end + 1, 200):
        hi = min(lo + 199, end)
        hashes = rpc.batch([("getblockhash", [h]) for h in range(lo, hi + 1)])
        heads = rpc.batch([("getblockheader", [h, True]) for h in hashes])
        for h in heads:
            total += 1
            if senaliza(h["version"]):
                n += 1
    return n, total


# --------------------------------------------------------------------------
def auditar_params(cli):
    print("\n[1] Parametros del BIP contra el .mediawiki oficial")
    bip = cli.get("/api/params").get_json()["bip"]
    esperado = {
        "name": "reduced_data", "bit": 4, "starttime": 1764547200,
        "period": 2016, "threshold_num": 1109,
        "mandatory_start": 961632, "mandatory_end": 963647,
        "forced_lockin": 963648, "activation_height": 965664,
        "max_activation_height": 965664, "active_duration": 52416,
    }
    for k, v in esperado.items():
        if bip.get(k) != v:
            fallo(f"params.{k} = {bip.get(k)}, esperado {v}")
    if bip.get("mandatory_start", 0) % 2016 != 0:
        fallo("mandatory_start no cae en frontera de periodo")
    if bip.get("activation_height", 0) - bip.get("forced_lockin", 0) != 2016:
        fallo("entre lock-in y activacion no hay exactamente un periodo")
    if not FALLOS:
        ok(f"los {len(esperado)} parametros coinciden")
    return bip


def auditar_miners(cli, bip, node):
    print(f"\n[2] Señalizacion del periodo en curso (nodo {node})")
    m = esperar(cli, f"/api/miners?node={node}")
    if not m.get("ok"):
        fallo(f"/api/miners no responde: {m.get('error')}")
        return None
    p = m["period"]

    # 2a. recuento independiente
    rpc = main._rpc(node)
    n, total = contar_periodo(rpc, p["start"], m["tip"])
    if n != m["signalling_blocks"]:
        fallo(f"señalizan: panel {m['signalling_blocks']}, recuento propio {n}")
    else:
        ok(f"recuento independiente coincide: {n} bloques")
    if total != p["scanned"]:
        fallo(f"escaneados: panel {p['scanned']}, recuento propio {total}")

    # 2b. Contra el contador de consenso de la implementacion de referencia.
    #     Ojo: el despliegue reduced_data solo existe en el nodo que aplica
    #     BIP-110. Pedirselo al canonico no falla, simplemente no esta, y la
    #     mejor prueba cruzada que tenemos se saltaria en silencio. Mientras
    #     las cadenas no se hayan separado los dos nodos ven los mismos
    #     bloques, asi que el contador del Knots vale para contrastar.
    hecho = False
    for cand in ("knots", "core"):
        if not main._node_configured(cand):
            continue
        try:
            dep = main._rpc(cand).call("getdeploymentinfo")["deployments"]["reduced_data"]
        except Exception:
            continue
        st = dep["bip9"]["statistics"]
        hecho = True
        if st["count"] != m["signalling_blocks"]:
            fallo(f"getdeploymentinfo del nodo {cand} cuenta {st['count']}, "
                  f"el panel {m['signalling_blocks']}")
        else:
            ok(f"contador de consenso del nodo {cand} coincide: {st['count']} "
               f"(bit {dep['bip9']['bit']}, estado {dep['bip9']['status']})")
        if st["threshold"] != m["threshold_blocks"]:
            fallo(f"umbral: nodo {st['threshold']}, panel {m['threshold_blocks']}")
        else:
            ok(f"umbral del nodo coincide: {st['threshold']}")
        if abs(st["elapsed"] - p["scanned"]) > 2:
            fallo(f"elapsed del nodo {st['elapsed']} vs escaneados {p['scanned']}")
        break
    if not hecho:
        fallo("ningun nodo expone el despliegue reduced_data: sin contraste "
              "contra la implementacion de referencia. Configura el nodo Knots.")

    # 2c. coherencia interna de los porcentajes
    if p["scanned"]:
        esperado = round(m["signalling_blocks"] / p["scanned"] * 100, 4)
        if not casi(m["pct_of_scanned"], esperado, 0.0001):
            fallo(f"pct_of_scanned {m['pct_of_scanned']} != {esperado}")
        else:
            ok(f"pct_of_scanned coherente ({m['pct_of_scanned']}%)")
    esperado = round(m["signalling_blocks"] / bip["period"] * 100, 4)
    if not casi(m["pct_of_period"], esperado, 0.0001):
        fallo(f"pct_of_period {m['pct_of_period']} != {esperado}")

    # 2d. umbral y alcanzabilidad
    thr = round(bip["threshold_num"] / bip["period"] * 100, 2)
    if not casi(m["threshold_pct"], thr, 0.01):
        fallo(f"threshold_pct {m['threshold_pct']} != {thr}")
    else:
        ok(f"umbral {m['threshold_blocks']}/{bip['period']} = {m['threshold_pct']}%")
    maxp = m["signalling_blocks"] + p["remaining"]
    if maxp != m["max_possible"]:
        fallo(f"max_possible {m['max_possible']} != {maxp}")
    if (maxp >= m["threshold_blocks"]) != m["threshold_reachable"]:
        fallo("threshold_reachable no cuadra con max_possible")
    else:
        ok(f"alcanzable={m['threshold_reachable']} (maximo posible {maxp}, hace falta {m['threshold_blocks']})")

    # 2e. periodo bien delimitado
    if p["start"] != p["index"] * bip["period"]:
        fallo(f"inicio de periodo {p['start']} != index*{bip['period']}")
    if p["end"] - p["start"] + 1 != bip["period"]:
        fallo("el periodo no mide 2016 bloques")
    if p["scanned"] + p["remaining"] != bip["period"]:
        fallo(f"escaneados+restantes = {p['scanned']+p['remaining']}, deberia ser {bip['period']}")
    else:
        ok(f"periodo {p['index']}: {p['scanned']} escaneados + {p['remaining']} restantes = {bip['period']}")

    # 2f. la atribucion por pool suma lo mismo que el recuento
    suma = sum(m["signalling_by_pool"].values())
    if suma != m["signalling_blocks"]:
        fallo(f"signalling_by_pool suma {suma}, señalizan {m['signalling_blocks']}")
    else:
        ok(f"atribucion por pool suma correcto: {m['signalling_by_pool']}")
    return m


def auditar_history(cli, bip, m):
    print("\n[3] Historico de periodos cerrados")
    h = esperar(cli, "/api/history")
    if not h.get("ok"):
        fallo(f"/api/history no responde: {h.get('error')}")
        return
    actual = m["period"]["index"]
    for per in h["periods"]:
        if per["period"] >= actual:
            fallo(f"el periodo {per['period']} NO esta cerrado (el actual es {actual})")
        if per["blocks"] != bip["period"]:
            fallo(f"periodo {per['period']} tiene {per['blocks']} bloques, no {bip['period']}")
        esperado = round(per["signalling"] / bip["period"] * 100, 4)
        if not casi(per["pct"], esperado, 0.0001):
            fallo(f"pct del periodo {per['period']}: {per['pct']} != {esperado}")
        if sum(per["by_pool"].values()) != per["signalling"]:
            fallo(f"by_pool del periodo {per['period']} no suma {per['signalling']}")
    ok(f"{len(h['periods'])} periodos cerrados, todos con {bip['period']} bloques y % coherente")

    if sum(p["signalling"] for p in h["periods"]) != h["signalling_blocks"]:
        fallo("el total de señalizacion no suma los periodos")
    if sum(p["blocks"] for p in h["periods"]) != h["total_blocks"]:
        fallo("el total de bloques no suma los periodos")
    if sum(h["by_pool"].values()) != h["signalling_blocks"]:
        fallo("by_pool agregado no suma el total de señalizacion")
    if h["by_pool"] and max(h["by_pool"].values()) != h["top_pool_blocks"]:
        fallo("top_pool_blocks no es el maximo de by_pool")
    if h["other_pools"] != max(0, len(h["by_pool"]) - 1):
        fallo(f"other_pools {h['other_pools']} != {max(0, len(h['by_pool'])-1)}")
    ok(f"totales: {h['signalling_blocks']} de {h['total_blocks']} = {h['signalling_pct']}% | "
       f"lider {h['top_pool']} {h['top_pool_blocks']} | otros {h['other_pools']}")

    # recuento independiente del ultimo periodo cerrado
    per = h["periods"][-1]
    n, total = contar_periodo(main._rpc(), per["start"], per["end"])
    if n != per["signalling"]:
        fallo(f"periodo {per['period']}: cache dice {per['signalling']}, recuento propio {n}")
    else:
        ok(f"recuento independiente del periodo {per['period']}: {n} de {total}")
    return h


def auditar_pools(cli):
    print("\n[4] Cuota de pools")
    p = esperar(cli, "/api/pools")
    if not p.get("ok"):
        fallo(f"/api/pools no responde: {p.get('error')}")
        return
    rows = p["pools"]
    bloques = sum(r["blocks"] for r in rows)
    if bloques != p["sample_blocks"]:
        fallo(f"los pools suman {bloques} bloques, muestra {p['sample_blocks']}")
    else:
        ok(f"los {len(rows)} pools suman los {bloques} bloques de la muestra")
    suma = sum(r["share_pct"] for r in rows)
    if abs(suma - 100) > 0.5:
        fallo(f"las cuotas suman {suma}%, deberian sumar 100%")
    else:
        ok(f"cuotas suman {round(suma,2)}%")
    for r in rows:
        esperado = round(r["blocks"] / p["sample_blocks"] * 100, 2)
        if not casi(r["share_pct"], esperado, 0.01):
            fallo(f"cuota de {r['pool']}: {r['share_pct']} != {esperado}")
        if r["signalling_blocks"] > r["blocks"]:
            fallo(f"{r['pool']} señaliza mas bloques de los que mina")
        if r["signals"] != (r["signalling_blocks"] > 0):
            fallo(f"{r['pool']}: signals no cuadra con signalling_blocks")
    sinnombre = {"Desconocido", "Sin etiqueta"}
    ident = len([r for r in rows if r["pool"] not in sinnombre])
    if ident != p["pools_identified"]:
        fallo(f"pools_identified {p['pools_identified']} != {ident}")
    noatr = sum(r["blocks"] for r in rows if r["pool"] in sinnombre)
    if noatr != p["unattributed_blocks"]:
        fallo(f"unattributed_blocks {p['unattributed_blocks']} != {noatr}")
    else:
        ok(f"{ident} pools identificados, {p['unattributed_pct']}% sin atribuir")
    if p["to_height"] - p["from_height"] + 1 != p["sample_blocks"]:
        fallo("el rango de alturas no cuadra con sample_blocks")
    return p


def auditar_chain(cli):
    print("\n[5] Comparacion de las dos cadenas")
    c = esperar(cli, "/api/chain")

    # Un error tiene que explicarse solo. Si lo que sale es el texto pelado
    # de una excepcion de Python, quien lo lea no sabra por donde empezar.
    # Paso de verdad: /api/chain devolvio {"error": "'knots'"}, que es un
    # KeyError convertido en cadena y no dice absolutamente nada.
    for donde, err in [("raiz", (c or {}).get("error"))] + \
                      [(n, v.get("error")) for n, v in (c or {}).get("nodes", {}).items()]:
        if err and len(str(err)) < 25 and not str(err)[0].isupper():
            fallo(f"mensaje de error inutil en {donde}: {err!r}")
    if not c.get("ok"):
        fallo(f"/api/chain no responde: {c.get('error')}")
        return
    if c.get("single_node"):
        aviso("solo hay un nodo configurado: no se puede auditar la comparacion")
        return c
    core, knots = c["nodes"]["core"], c["nodes"]["knots"]
    if not (core.get("ok") and knots.get("ok")):
        fallo("algun nodo no responde")
        return c

    if core["enforces"]:
        fallo("el nodo canonico APLICA BIP-110: no debe ser el canonico")
    else:
        ok(f"canonico {core['subversion']} no aplica BIP-110")
    if not knots["enforces"]:
        fallo("el nodo secundario NO aplica BIP-110: la comparacion no detectaria nada")
    else:
        ok(f"secundario {knots['subversion']} aplica BIP-110")

    # comprobacion independiente: mismo hash a la misma altura
    a, b = main._rpc("core"), main._rpc("knots")
    comun = min(core["tip"], knots["tip"])
    ha, hb = a.call("getblockhash", comun), b.call("getblockhash", comun)
    if (ha == hb) != (c["state"] != "split"):
        fallo(f"estado '{c['state']}' no cuadra con la comparacion de hashes en {comun}")
    else:
        ok(f"estado '{c['state']}' confirmado comparando el bloque {comun}")
    if c["state"] != "split" and core["hash"] != knots["hash"] and core["tip"] == knots["tip"]:
        fallo("misma altura, distinto hash, y el estado no es 'split'")

    w1 = int(core.get("chainwork") or "0", 16)
    w2 = int(knots.get("chainwork") or "0", 16)
    maj = c["majority"]["node"]
    if (w1 >= w2 and maj != "core") or (w2 > w1 and maj != "knots"):
        fallo("la cadena mayoritaria no es la de mas trabajo acumulado")
    else:
        ok(f"mayoritaria por trabajo acumulado: {maj}")
    return c


def auditar_nodes(cli):
    print("\n[6] Sondeo de nodos")
    n = esperar(cli, "/api/nodes")
    if not n.get("ok"):
        aviso(f"/api/nodes no devuelve datos: {n.get('error')}")
        return
    total = n["total_reachable_sampled"]
    for campo in ("by_client", "by_network", "by_rules"):
        suma = sum(n.get(campo, {}).values())
        if suma != total:
            fallo(f"{campo} suma {suma}, alcanzados {total}")
    ok(f"by_client, by_network y by_rules suman los {total} alcanzados")
    for k, v in n.get("by_client", {}).items():
        esperado = round(v / total * 100, 2) if total else 0
        if not casi(n["pct"].get(k), esperado, 0.01):
            fallo(f"pct de {k}: {n['pct'].get(k)} != {esperado}")
    for k, v in n.get("by_rules", {}).items():
        esperado = round(v / total * 100, 2) if total else 0
        if not casi(n["pct_rules"].get(k), esperado, 0.01):
            fallo(f"pct_rules de {k}: {n['pct_rules'].get(k)} != {esperado}")
    ok("porcentajes coherentes con los recuentos")
    solapan = set(n.get("networks_probed", [])) & set(n.get("networks_skipped", []))
    if solapan:
        fallo(f"redes a la vez sondeadas y no sondeadas: {solapan}")
    fuera = set(n.get("by_network", {})) - set(n.get("networks_probed", []))
    if fuera:
        fallo(f"hay nodos de redes que se declaran no sondeadas: {fuera}")
    else:
        ok(f"redes sondeadas {n.get('networks_probed')} / fuera {n.get('networks_skipped')}")
    if total < 50:
        aviso(f"muestra de solo {total} nodos: no citar porcentajes de aqui")
    return n


def auditar_simulador(cli):
    print("\n[7] Simulador de cadena minoritaria")
    for share in (0.02, 0.1, 0.5):
        s = cli.get(f"/api/simulate?share={share}").get_json()
        intervalo = 600 / share
        if not casi(s["interval_seconds"], intervalo, 1):
            fallo(f"share {share}: intervalo {s['interval_seconds']} != {intervalo}")
        if not casi(s["blocks_per_day"], round(86400 / intervalo, 2), 0.01):
            fallo(f"share {share}: bloques por dia incoherentes")
        if not casi(s["retarget_days"], round(intervalo * 2016 / 86400, 1), 0.1):
            fallo(f"share {share}: dias hasta el reajuste incoherentes")
        if s["viable"] != (share >= 0.5):
            fallo(f"share {share}: viable={s['viable']}")
    ok("intervalo, bloques por dia y reajuste coherentes para 2%, 10% y 50%")
    s = cli.get("/api/simulate?share=0.02").get_json()
    ok(f"con el 2%: un bloque cada {s['interval_hours']} h, reajuste en {s['retarget_days']} dias")


def auditar_cruce(cli):
    print("\n[8] Cruce entre endpoints")
    m = cli.get("/api/miners").get_json()
    h = esperar(cli, "/api/history")
    if m.get("ok") and h.get("ok"):
        if h["periods"] and h["periods"][-1]["period"] >= m["period"]["index"]:
            fallo("el historico incluye el periodo en curso")
        else:
            ok(f"historico llega hasta el {h['periods'][-1]['period']}, en curso el {m['period']['index']}")
    c = esperar(cli, "/api/chain")
    if m.get("ok") and c.get("ok") and c["nodes"]["core"].get("ok"):
        if abs(m["tip"] - c["nodes"]["core"]["tip"]) > 2:
            fallo(f"/api/miners tip {m['tip']} vs /api/chain tip {c['nodes']['core']['tip']}")
        else:
            ok("la altura coincide entre /api/miners y /api/chain")
    mk = esperar(cli, "/api/miners?node=knots")
    if m.get("ok") and mk.get("ok"):
        if c.get("state") == "pre_split" and m["signalling_blocks"] != mk["signalling_blocks"]:
            fallo(f"los dos nodos discrepan en la señalizacion: "
                  f"core {m['signalling_blocks']} vs knots {mk['signalling_blocks']}")
        else:
            ok(f"los dos nodos cuentan lo mismo: {m['signalling_blocks']} bloques")


def main_audit():
    cli = main.app.test_client()
    node = "core"
    print("=" * 66)
    print("AUDITORIA DE DATOS DEL PANEL BIP-110")
    print("=" * 66)
    bip = auditar_params(cli)
    m = auditar_miners(cli, bip, node)
    if m:
        auditar_history(cli, bip, m)
    auditar_pools(cli)
    auditar_chain(cli)
    auditar_nodes(cli)
    auditar_simulador(cli)
    auditar_cruce(cli)
    print("\n" + "=" * 66)
    print(f"RESULTADO: {len(FALLOS)} fallos, {len(AVISOS)} avisos")
    for f in FALLOS:
        print("  FALLO  " + f)
    for a in AVISOS:
        print("  AVISO  " + a)
    return 1 if FALLOS else 0


if __name__ == "__main__":
    sys.exit(main_audit())
