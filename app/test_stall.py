#!/usr/bin/env python3
"""
Un nodo parado no es una separacion, y tampoco es "todo coincide".

Existe por un hueco encontrado el 2026-08-08, con 67 bloques por delante de
la altura obligatoria. A partir de esa altura un nodo BIP-110 solo acepta
bloques que señalicen Y cuyos antepasados desde ahi tambien señalicen. Con
la señalizacion en el 2,5%, lo primero que hace no es bifurcarse: se queda
quieto, porque no hay ningun bloque valido para el. Su punta se congela
mientras la otra avanza.

El hash a la altura comun sigue coincidiendo, asi que el estado `pre_split`
es CORRECTO y no se toca. Lo que faltaba era decir la distancia: el panel
habria dicho "las dos cadenas coinciden" con un nodo congelado desde hacia
horas. Verdad, y engaña.

`stress.js` no cubre esto porque trabaja con datos sinteticos: la decision
de marcar `lagging` la toma el backend. Aqui se ejercita `_build_chains()`
de verdad, con dos nodos falsos.

Uso: python3 test_stall.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("WARM_ON_START", "false")
import main                                                  # noqa: E402

AHORA = int(time.time())


class NodoFalso:
    """Lo justo de un nodo: su punta, su hash y la hora de sus bloques."""

    def __init__(self, tip, hash_por_altura, hora_punta=None):
        self.tip = tip
        self.hash_por_altura = hash_por_altura
        self.hora_punta = hora_punta

    def batch(self, _peticiones):
        return ({"blocks": self.tip,
                 "bestblockhash": self.hash_por_altura(self.tip),
                 "chainwork": "0f"},
                {"subversion": "/falso/", "localservicesnames": []})

    def call(self, metodo, *a):
        if metodo == "getblockhash":
            return self.hash_por_altura(a[0])
        if metodo == "getblockheader":
            return {"time": self.hora_punta}
        raise AssertionError(metodo)


def misma_cadena(h):
    """Las dos ramas comparten historia: el hash solo depende de la altura."""
    return "h%d" % h


fallos = 0


def comprobar(nombre, ok, extra=""):
    global fallos
    if not ok:
        fallos += 1
    print("%s  %-56s %s" % ("ok   " if ok else "FALLO", nombre, extra))


def escenario(tip_core, tip_knots, hora_punta_knots=None):
    """Monta los dos nodos y devuelve lo que responderia /api/chain."""
    nodos = {
        "core": NodoFalso(tip_core, misma_cadena),
        "knots": NodoFalso(tip_knots, misma_cadena, hora_punta_knots),
    }
    main._rpc = lambda n: nodos[n]
    main._node_configured = lambda n: True
    main._load_state = lambda: {}
    main._save_state = lambda s: None
    main.transport_of = lambda u: "tor"
    main._active_url = lambda n: ""
    return main._build_chains()


# --- 1. Operacion normal: un bloque recien minado es propagacion, no averia.
d = escenario(961700, 961699, AHORA - 120)
comprobar("un bloque de hueco reciente no se reporta como retraso",
          d["state"] == "pre_split" and not d.get("lagging"),
          "hueco=%s" % d.get("height_gap"))

# --- 1b. EL CASO DEL 2026-08-08: un solo bloque de hueco, pero congelado.
#         Mirando solo el tamaño, esto pasaba por "coinciden".
d = escenario(961632, 961631, AHORA - 2400)
comprobar("un hueco de UN bloque que lleva 40 min cuenta como paron",
          d.get("lagging") == "knots", "lagging=%s" % d.get("lagging"))
comprobar("y sigue sin ser una separacion", d["state"] == "pre_split")

# --- 2. Los dos a la misma altura: nada que decir.
d = escenario(961700, 961700)
comprobar("sin hueco no hay nada que decir",
          d["state"] == "pre_split" and not d.get("lagging") and d["height_gap"] == 0)

# --- 3. EL CASO DE ESTA NOCHE: el nodo BIP-110 congelado.
d = escenario(961701, 961631, AHORA - 41400)
comprobar("un nodo congelado se marca aunque los hashes coincidan",
          d.get("lagging") == "knots", "lagging=%s" % d.get("lagging"))
comprobar("y NO se llama separacion, porque no lo es",
          d["state"] == "pre_split", "estado=%s" % d["state"])
comprobar("se dice cuantos bloques de distancia",
          d.get("height_gap") == 70, "hueco=%s" % d.get("height_gap"))
comprobar("y cuanto lleva sin avanzar",
          11.0 < (d["nodes"]["knots"].get("seconds_since_last_block") or 0) / 3600 < 11.9,
          "%.1f h" % ((d["nodes"]["knots"].get("seconds_since_last_block") or 0) / 3600))

# --- 4. Al reves: si el que se queda atras es el canonico, tambien se dice.
d = escenario(961631, 961701, None)
comprobar("si el rezagado es el otro nodo, se marca ese",
          d.get("lagging") == "core", "lagging=%s" % d.get("lagging"))

# --- 5. Solo al nodo rezagado se le pregunta la hora. El otro no paga nada.
d = escenario(961701, 961631, AHORA - 3600)
comprobar("al nodo que va bien no se le anota hora de punta",
          d["nodes"]["core"].get("seconds_since_last_block") is None)

# --- 6. Si el nodo rezagado no contesta la hora, no se inventa nada.
d = escenario(961701, 961631, None)
comprobar("sin hora de punta, el retraso se sigue diciendo",
          d.get("lagging") == "knots")
comprobar("y no se imprime un tiempo falso",
          d["nodes"]["knots"].get("seconds_since_last_block") is None)

# --- 7. El umbral es pequeño y positivo. Si alguien lo sube sin querer, esto
#        avisa: con un umbral grande, la noche de la altura obligatoria el
#        panel se callaria durante horas.
comprobar("el umbral sigue siendo pequeño", 2 <= main.STALL_GAP <= 6,
          "STALL_GAP=%d" % main.STALL_GAP)


# --- 8. CON LAS CADENAS SEPARADAS, EL RITMO SE MIDE SOBRE EL TIEMPO.
#
# La media de los INTERVALOS miente en cuanto una rama se para: sus dos
# bloques tardaron 1,1 h entre uno y otro, asi que el panel decia "un bloque
# cada 1,1 horas" al lado de "ultimo bloque hace 15 h". Ciertas las dos y
# contradiciendose en la misma tarjeta.
#
# Dividiendo el tiempo desde el corte entre los bloques hechos, una cadena
# sana no cambia y una parada se degrada sola.
FORK_H = 961631
T_FORK = AHORA - 61200          # el corte, hace 17 horas


class DosRamas:
    """Nodo de una rama. El hash lleva la altura dentro, asi que la hora de
    cualquier bloque se puede derivar sin tabla aparte."""

    def __init__(self, tip, marca, seg_por_bloque):
        self.tip, self.marca, self.spb = tip, marca, seg_por_bloque

    def _hash(self, h):
        return ("%s%d" % (self.marca, h)) if h > FORK_H else "comun%d" % h

    def batch(self, _p):
        return ({"blocks": self.tip, "bestblockhash": self._hash(self.tip),
                 "chainwork": "0f" if self.marca == "a" else "0a"},
                {"subversion": "/falso/", "localservicesnames": []})

    def call(self, metodo, *a):
        if metodo == "getblockhash":
            return self._hash(a[0])
        if metodo == "getblockheader":
            h = int("".join(c for c in a[0] if c.isdigit()))
            return {"time": T_FORK + max(0, h - FORK_H) * self.spb}
        raise AssertionError(metodo)


ramas = {"core": DosRamas(961728, "a", 631),      # 97 bloques en 17 h
         "knots": DosRamas(961633, "b", 4069)}    # 2 bloques, y parada
main._rpc = lambda n: ramas[n]
main._node_configured = lambda n: True
main._load_state = lambda: {}
main._save_state = lambda s: None
main.transport_of = lambda u: "tor"
main._active_url = lambda n: ""
d = main._build_chains()

comprobar("se detecta la separacion", d["state"] == "split",
          "corte en %s" % d.get("split_height"))
maj, mino = d.get("majority") or {}, d.get("minority") or {}
comprobar("la mayoritaria sale como la de mas trabajo", maj.get("node") == "core")

# 97 bloques en 17 h son 10,5 min. Este numero casi no cambia con el metodo
# nuevo, y esa es la gracia: solo se mueve donde hacia falta.
comprobar("cadena sana: el ritmo sigue siendo el de siempre",
          600 < (maj.get("avg_interval_sec") or 0) < 700,
          "%.0f s/bloque" % (maj.get("avg_interval_sec") or 0))

# 2 bloques en 17 h son 8,5 h, no 1,1 h.
h_min = (mino.get("avg_interval_sec") or 0) / 3600
comprobar("cadena parada: el ritmo recoge el tiempo sin producir",
          8.0 < h_min < 9.0, "%.1f h/bloque" % h_min)
comprobar("y NO es la media entre sus dos bloques (1,1 h)", h_min > 2)
comprobar("la base son los bloques propios desde el corte",
          mino.get("interval_blocks") == 2, "n=%s" % mino.get("interval_blocks"))


# --- 9. LA DIRECCION DEL NODO NO SALE EN NINGUNA RESPUESTA PUBLICA.
#
# El 2026-08-09 la .onion del nodo canonico aparecio entera en /api/chain.
# La rama que gestiona "este nodo no responde" copiaba el texto crudo de la
# excepcion, y ese texto llevaba las URLs probadas dentro. Todas las demas
# rutas limpiaban; bastaba una que no.
#
# Se comprueba de punta a punta: un nodo que falla con la direccion dentro
# del error, y la respuesta entera mirada en busca de cualquier rastro.
# NUNCA una direccion real aqui, ni siquiera en una prueba.
# Esta cadena se escribio con la .onion de verdad del nodo y acabo
# publicada en GitHub, en la misma prueba que existe para impedir
# justo eso. Lo que no debe salir no se escribe en ningun sitio, y un
# fichero de pruebas es un sitio.
ONION = "aaaaaaaaaaaaaaaaaaaaaaaaaaejemplodeprueba234567abcdefghij.onion"


class NodoQueFalla:
    def batch(self, _p):
        raise RuntimeError(
            "Ninguna direccion del nodo 'core' responde. Probadas: "
            "http://%s:8332 -> SOCKSHTTPConnectionPool(host='%s', port=8332): "
            "Max retries exceeded" % (ONION, ONION))

    def call(self, *a):
        raise RuntimeError("http://%s:8332 no responde" % ONION)


rotos = {"core": NodoQueFalla(), "knots": DosRamas(961633, "b", 4069)}
main._rpc = lambda n: rotos[n]
main._node_configured = lambda n: True
main._load_state = lambda: {}
main._save_state = lambda s: None
main.transport_of = lambda u: "tor"
main._active_url = lambda n: ""
d = main._build_chains()

crudo = json.dumps(d, default=str)
comprobar("la .onion no aparece en la respuesta", ONION not in crudo)
comprobar("ni el trozo reconocible de la direccion", ONION[:20] not in crudo)
comprobar("ni ninguna otra cosa acabada en .onion",
          ".onion" not in crudo, crudo[:90] if ".onion" in crudo else "")
comprobar("y aun asi se dice que ese nodo no responde",
          d["nodes"]["core"].get("ok") is False and
          bool(d["nodes"]["core"].get("error")),
          d["nodes"]["core"].get("error", "")[:60])

print()
print("sin fallos" if not fallos else "%d fallos" % fallos)
sys.exit(1 if fallos else 0)
