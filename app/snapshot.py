#!/usr/bin/env python3
"""
Hace la foto fija con la que se queda el sitio.

El observador se termino el 2026-09-05. Mientras el panel siguio vivo contra
los nodos pasaba algo que no se sostiene: la pagina decia "esto ya no se
actualiza" mientras la altura de bloque subia sola delante del lector. Un
cartel que la propia pagina desmiente no lo cree nadie, y hace bien.

Esto mide todo una ultima vez y lo guarda en `CACHE_DIR/snapshot.json`. Con
`FROZEN=true` en el entorno, la aplicacion sirve ESO y no vuelve a hablar con
ningun nodo.

Dos cosas a proposito:

  - La foto lleva `taken_at`, y la interfaz lo enseña. Una foto que no dice
    su fecha se lee como si fuera de ahora, que es justo el engaño que este
    proyecto existe para no cometer.
  - NO se congela `/api/health`. Sin nodos que vigilar no hay salud que
    reportar, y guardar un "todo correcto" de hace meses seria afirmar hoy
    algo que no se ha comprobado hoy.

Uso:  python3 snapshot.py            (con el .env cargado, ver audit_env.py)
      FROZEN=true docker compose up -d --build
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# La foto hay que tomarla con los nodos vivos, asi que aqui nunca congelado.
os.environ["FROZEN"] = "false"
os.environ.setdefault("WARM_ON_START", "false")

import main                                                  # noqa: E402

# Cada entrada es la clave de cache y el constructor que la llena. Son los
# mismos que usa la aplicacion: la foto no puede salir de un camino distinto
# del que se esta fotografiando.
PIEZAS = [
    ("chains",   lambda: main._build_chains()),
    ("miners",   lambda: main._build_miners(main.DEFAULT_NODE)),
    ("pools",    lambda: main._build_pools(main.DEFAULT_NODE)),
    ("history",  lambda: main._build_history(main.DEFAULT_NODE)),
    ("nodes",    lambda: main._build_nodes()),
    ("timeline", lambda: main._build_timeline()),
]


def main_():
    # LA CLAVE TIENE QUE SER LA QUE LEE LA APLICACION, Y ESTO YA FALLO.
    #
    # La primera version guardaba "chain" y `/api/chain` lee "chains". La
    # foto se escribia entera y sin quejarse, y el endpoint caia al respaldo
    # como si ese dato no se hubiera medido nunca. Un fallo mudo, con el
    # sitio ya congelado, o sea en el peor momento para descubrirlo.
    #
    # `TTL` es la lista de claves reales, asi que se comprueba contra ella y
    # no contra una copia de esta lista, que es lo que se salio de sitio.
    desconocidas = [n for n, _ in PIEZAS if n not in main.TTL]
    if desconocidas:
        print("Estas claves no las lee nadie: %s" % ", ".join(desconocidas))
        print("Las que existen son: %s" % ", ".join(sorted(main.TTL)))
        return 1

    salida = {"taken_at": int(time.time()), "endpoints": {}}
    fallos = []
    for nombre, hacer in PIEZAS:
        t0 = time.time()
        try:
            d = hacer()
        except Exception as e:                               # noqa: BLE001
            print("FALLO  %-10s %s" % (nombre, type(e).__name__))
            fallos.append(nombre)
            continue
        # Una foto no puede llevar dentro "calculando" ni "datos viejos":
        # esos campos describen un panel en marcha, y este no lo esta.
        for k in ("stale", "stale_seconds", "computing"):
            d.pop(k, None)
        salida["endpoints"][nombre] = d
        print("ok     %-10s %5.1f s   ok=%s" % (nombre, time.time() - t0, d.get("ok")))

    if fallos:
        print("\nNo se guarda nada: han fallado %s." % ", ".join(fallos))
        print("Una foto a medias es peor que ninguna, porque parece completa.")
        return 1

    if not main.CACHE_DIR:
        print("\nNo hay CACHE_DIR donde guardarla.")
        return 1
    destino = os.path.join(main.CACHE_DIR, "snapshot.json")
    tmp = destino + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(salida, fh)
    os.replace(tmp, destino)
    print("\nFoto guardada en %s" % destino)
    print("Ahora: FROZEN=true, y el sitio deja de hablar con los nodos.")
    return 0


if __name__ == "__main__":
    sys.exit(main_())
