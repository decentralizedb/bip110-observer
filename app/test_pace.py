#!/usr/bin/env python3
"""
El ritmo de una rama se mide con bloques de ESA rama.

Existe por un fallo que estuvo en produccion sin que se notara, y que no se
habria notado hasta el dia de la separacion, que es cuando peor viene.
`_pace` miraba los ultimos 144 bloques sin preguntarse donde empieza la
rama. Recien separadas las cadenas, la rama minoritaria tiene tres o cuatro
bloques propios, asi que los otros 140 son ANTERIORES a la bifurcacion:
comunes a las dos cadenas y minados a diez minutos.

Medido aqui con una cadena simulada: una rama que va de verdad a 25.200
segundos por bloque salia a 1.283. Veinte veces mas rapida, en la cifra que
sostiene el mensaje del panel, y la rama habria parecido sana durante
semanas justo cuando lo que importa es ver que no lo esta.

No se puede comprobar contra el nodo, porque la situacion todavia no existe.
Por eso la cadena es simulada: es la unica forma de estrenar el caso antes
de que llegue.

Uso: python3 test_pace.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("WARM_ON_START", "false")
import main                                                 # noqa: E402

FORK = 961631
LENTO = 7 * 3600        # la rama minoritaria: un bloque cada 7 horas
NORMAL = 600            # antes de la bifurcacion: diez minutos
T0 = 1000000000


class NodoFalso:
    """Bloques comunes a 10 min hasta FORK, y despues a 7 horas."""

    def __init__(self, tip):
        self.tip = tip

    def call(self, metodo, *a):
        if metodo == "getblockhash":
            return "h%d" % a[0]
        if metodo == "getblockheader":
            h = int(a[0][1:])
            if h <= FORK:
                return {"time": T0 + h * NORMAL}
            return {"time": T0 + FORK * NORMAL + (h - FORK) * LENTO}
        raise AssertionError(metodo)


fallos = 0


def comprobar(nombre, ok, extra=""):
    global fallos
    if not ok:
        fallos += 1
    print("%s  %-52s %s" % ("ok   " if ok else "FALLO", nombre, extra))


nodo = NodoFalso(tip=FORK + 4)

# Sin suelo: lo que hacia antes. Se cuela en los bloques comunes.
viejo, _, _ = main._pace(nodo, FORK + 4)
comprobar("sin suelo el ritmo sale engañosamente rapido",
          viejo is not None and viejo < 2 * 3600, "%.0f s/bloque" % (viejo or 0))

# Con suelo: solo los cuatro bloques de la rama.
nuevo, ultima, n = main._pace(nodo, FORK + 4, suelo=FORK)
comprobar("con suelo mide el ritmo real de la rama",
          nuevo is not None and abs(nuevo - LENTO) < 1, "%.0f s/bloque" % (nuevo or 0))
comprobar("y devuelve la hora del ultimo bloque", ultima is not None)
comprobar("y sobre cuantos bloques va la media", n == 4, "n=%d" % n)

# Un solo bloque propio: hay un intervalo, pero es UNA muestra y hay que
# poder decirlo. Por eso se devuelve n, no solo la media.
ritmo1, ultima1, n1 = main._pace(NodoFalso(tip=FORK + 1), FORK + 1, suelo=FORK)
comprobar("con un bloque propio mide, pero avisa de que es una muestra",
          ritmo1 is not None and n1 == 1, "n=%d" % n1)
comprobar("y dice cuando fue ese bloque", ultima1 is not None)

# Cero bloques propios: la rama todavia no ha producido nada.
ritmo0, ultima0, n0 = main._pace(NodoFalso(tip=FORK), FORK, suelo=FORK)
comprobar("sin bloques propios no inventa intervalo",
          ritmo0 is None and n0 == 0)
comprobar("pero si la hora del ultimo bloque comun", ultima0 is not None)

# Y en la cadena mayoritaria, con muchos bloques, el suelo no estorba.
maj, _, nmaj = main._pace(NodoFalso(tip=FORK + 300), FORK + 300, suelo=FORK)
comprobar("la ventana de 144 sigue mandando cuando hay bloques de sobra",
          maj is not None and abs(maj - LENTO) < 1 and nmaj == 144, "n=%d" % nmaj)

print()
print("sin fallos" if not fallos else "%d fallos" % fallos)
sys.exit(1 if fallos else 0)
