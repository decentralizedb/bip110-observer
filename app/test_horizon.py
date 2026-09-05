#!/usr/bin/env python3
"""
Un silencio que no podemos oir no es un silencio.

El 2026-08-30 la cadena del BIP-110 cambio de proof of work en el bloque
961.640. El nodo Knots propio es anterior, no implementa BLAKE2b, y su punta
se quedo clavada en el 961.639 para siempre.

El ritmo de una rama se mide dividiendo el tiempo transcurrido entre los
bloques producidos, y eso estaba bien mientras el reloj y el contador
miraran lo mismo. Con el contador congelado, la cifra se degrada sola hacia
el infinito: el 5 de septiembre la tarjeta decia "un bloque cada 83,1 h" y
subiendo. No mide la cadena. Mide cuanto llevamos sin poder verla.

Y empuja en la direccion de nuestra propia tesis, que es lo que lo hace
peligroso: el numero parece objetivo y dice justo lo que nos gustaria oir.

Aqui se comprueban las dos mitades: que en el horizonte se deja de contar el
reloj, y que fuera del horizonte se sigue contando como siempre. La segunda
importa tanto como la primera, porque una condicion que se cumple siempre
apaga la medida entera sin que nadie lo note.

Uso: python3 test_horizon.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("WARM_ON_START", "false")
import main                                                  # noqa: E402
import signaling                                             # noqa: E402

FORK = signaling.POW_FORK["height"]          # 961640
CORTE = 961632                               # donde se separaron las cadenas
T_CORTE = 1786217755                         # 8 ago 2026 20:12 UTC, medido
T_ULTIMO = 1787937269                        # 28 ago 2026 17:14 UTC, medido

fallos = 0


def comprobar(nombre, ok, extra=""):
    global fallos
    if not ok:
        fallos += 1
    print("%s  %-58s %s" % ("ok   " if ok else "FALLO", nombre, extra))


class NodoFalso:
    def __init__(self, tip, rama, hora_punta, aplica):
        self.tip = tip
        self.rama = rama
        self.hora_punta = hora_punta
        self.aplica = aplica

    def _hash(self, h):
        # Historia comun hasta el corte, y a partir de ahi cada uno la suya.
        return "h%d" % h if h < CORTE else "h%d-%s" % (h, self.rama)

    def batch(self, _p):
        return ({"blocks": self.tip,
                 "bestblockhash": self._hash(self.tip),
                 # La mayoritaria tiene mucho mas trabajo acumulado, que es
                 # como el panel decide cual es cual.
                 "chainwork": "ff" if self.rama == "maj" else "0f"},
                {"subversion": "/falso/",
                 "localservicesnames": ["REDUCED_DATA"] if self.aplica else []})

    def call(self, metodo, *a):
        if metodo == "getblockhash":
            return self._hash(a[0])
        if metodo == "getblockheader":
            return {"time": self.hora_punta}
        raise AssertionError(metodo)


def escenario(tip_knots, ahora):
    nodos = {
        "core": NodoFalso(965613, "maj", ahora - 300, aplica=False),
        "knots": NodoFalso(tip_knots, "min", T_ULTIMO, aplica=True),
    }
    main._rpc = lambda n: nodos[n]
    main._node_configured = lambda n: True
    main._load_state = lambda: {"split_height": CORTE, "split_time": T_CORTE,
                                "split_hashes": {}}
    main._save_state = lambda s: None
    main.transport_of = lambda u: "tor"
    main._active_url = lambda n: ""
    main.time = FakeTime(ahora)
    return main._build_chains()


class FakeTime:
    """Solo hace falta que el reloj avance a voluntad."""

    def __init__(self, ahora):
        self.ahora = ahora

    def time(self):
        return self.ahora


reloj_real = main.time
AHORA = int(time.time())

# --- 1. En el horizonte: la punta esta clavada un bloque antes del fork.
d = escenario(FORK - 1, AHORA)
mino = d.get("minority") or {}
comprobar("hay separacion", d.get("state") == "split", d.get("state"))
comprobar("la rama del BIP-110 se declara no medible",
          mino.get("measurable") is False, "measurable=%s" % mino.get("measurable"))
comprobar("y dice a que altura se le acaba la vista",
          mino.get("horizon_height") == FORK, "horizonte=%s" % mino.get("horizon_height"))
comprobar("y con que algoritmo se fue",
          mino.get("horizon_algo") == signaling.POW_FORK["algo"],
          mino.get("horizon_algo"))

# El ritmo se cierra en el ultimo bloque medido, no en el reloj de ahora.
esperado = (T_ULTIMO - T_CORTE) / float(FORK - 1 - CORTE)
comprobar("el ritmo se mide hasta el ultimo bloque que se pudo ver",
          mino.get("avg_interval_sec") is not None
          and abs(mino["avg_interval_sec"] - esperado) < 1,
          "%.1f h" % ((mino.get("avg_interval_sec") or 0) / 3600))

# --- 2. Y LO QUE IMPORTA: no se mueve porque pase el tiempo.
#        Esta es la prueba de verdad. Antes del arreglo, adelantar el reloj
#        una semana subia la cifra una semana entera.
d2 = escenario(FORK - 1, AHORA + 7 * 86400)
r1 = (d.get("minority") or {}).get("avg_interval_sec")
r2 = (d2.get("minority") or {}).get("avg_interval_sec")
comprobar("y una semana despues sigue siendo el mismo numero",
          r1 is not None and r1 == r2, "%s -> %s" % (r1, r2))

# --- 3. La mayoritaria no se ve afectada: ahi si cuenta el reloj.
maj1 = (d.get("majority") or {}).get("avg_interval_sec")
maj2 = (d2.get("majority") or {}).get("avg_interval_sec")
comprobar("la cadena que si podemos medir sigue contando el reloj",
          maj1 is not None and maj2 is not None and maj2 > maj1,
          "%s -> %s" % (maj1, maj2))
comprobar("y se declara medible",
          (d.get("majority") or {}).get("measurable") is True)

# --- 4. ROMPIENDO LA CONDICION A PROPOSITO: una rama parada ANTES del
#        horizonte no es ceguera nuestra, es un paron suyo, y ahi el reloj
#        tiene que seguir corriendo. Sin esta comprobacion, un `ciego` que
#        valiera siempre apagaria la medida entera sin avisar.
d3 = escenario(FORK - 2, AHORA)
d4 = escenario(FORK - 2, AHORA + 7 * 86400)
m3 = (d3.get("minority") or {}).get("avg_interval_sec")
m4 = (d4.get("minority") or {}).get("avg_interval_sec")
comprobar("una rama parada antes del horizonte SI se sigue midiendo",
          (d3.get("minority") or {}).get("measurable") is True)
comprobar("y ahi un paron suyo si degrada el ritmo, como debe",
          m3 is not None and m4 is not None and m4 > m3,
          "%s -> %s" % (m3, m4))

main.time = reloj_real
print()
if fallos:
    print("%d fallos" % fallos)
    sys.exit(1)
print("sin fallos")
