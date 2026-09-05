"""
Lo que dicen TERCEROS sobre la cadena BLAKE2b, que este panel no puede medir.

Este fichero existe para que la frontera se vea en el codigo y no solo en la
pantalla. Todo lo demas del proyecto sale de los nodos propios. Esto no, y no
puede salir de ahi: la cadena cambio de proof of work el 2026-08-30 en el
bloque 961.640 y el nodo propio, que es anterior, no puede validar ni uno de
sus bloques.

NO ROMPE LA REGLA DE "NADA DE TERCEROS", y conviene tener claro por que. Esa
regla prohibe que el panel DEPENDA de una API ajena estando en marcha: es una
decision de soberania, no una manía. Esto es lo contrario de una dependencia.
Son cifras copiadas a mano, con fecha, con fuente y congeladas, en una pagina
que documenta algo que ya termino. Es una cita, no una tuberia. Nada de este
fichero se consulta por red, ni ahora ni nunca.

Y son un CUARTO nivel epistemico, distinto de los tres del panel:

    dato verificable   cualquiera con un nodo obtiene el mismo numero
    estimacion         muestra o modelo nuestro, con supuestos explicitos
    muestra sesgada    no representa la poblacion, y se dice por que
    fuente externa     lo dice otro, no lo podemos comprobar, y ademas
                       lo dice alguien con interes en el asunto

Las dos fuentes que publican cifras son el sitio de promocion del fork y un
sitio que promueve minarlo. No se presentan como neutrales y no se van a
presentar aqui como neutrales.

Comprobado el 2026-09-05. Si alguien actualiza esto, que actualice `as_of`.
"""

# Quien lo dice. Se enseña en pantalla junto a cada cifra, no en un pie.
FUENTES = {
    "sitio": {
        "name": "btc-blake2b.org",
        "url": "https://btc-blake2b.org/",
        # Es el sitio de promocion del propio fork.
        "interest": "promoter",
    },
    "minero": {
        "name": "blake2bminer.com",
        "url": "https://blake2bminer.com/",
        # Promueve minar esa cadena.
        "interest": "promoter",
    },
    "prensa": {
        "name": "CryptoRank / Gate",
        "url": "https://cryptorank.io/news/feed/76fe3-bitcoin-hard-fork-failed-adam-back",
        "interest": "press",
    },
}

# `derived` marca lo que hemos calculado NOSOTROS a partir de sus cifras. Se
# separa a proposito: una resta nuestra sobre un numero redondeado por ellos
# no es una cifra suya, y presentarla como tal seria ascenderla de nivel.
CLAIMS = [
    {"key": "xFirstBlock", "value": 961640, "as_of": "2026-08-30", "src": "sitio"},
    {"key": "xHeight", "value": 967681, "as_of": "2026-09-04", "src": "minero"},
    {"key": "xHashrate", "value": 3.1, "unit": "PH/s", "as_of": "2026-09-04",
     "src": "minero"},
    {"key": "xDiffStart", "value": 30393776, "as_of": "2026-08-30", "src": "minero"},
    {"key": "xDiff1", "value": 17842860, "pct": -41.3, "height": 963648,
     "as_of": "2026-09-01", "src": "minero"},
    {"key": "xDiff2", "value": 71371438, "factor": 4, "height": 965664,
     "as_of": "2026-09-02", "src": "minero"},
    {"key": "xDiff3", "value": 285485753, "factor": 4, "height": 967680,
     "as_of": "2026-09-04", "src": "minero"},
    {"key": "xReward", "value": 3.13, "unit": "BTC", "as_of": "2026-08-31",
     "src": "minero"},
    {"key": "xFees", "value": 0.005, "unit": "BTC", "as_of": "2026-08-31",
     "src": "minero", "derived": True},
    {"key": "xMarket", "bid": 82, "ask": 190, "spread_pct": 131.7,
     "as_of": "2026-09-03", "src": "prensa"},
]

# Lo que se busco y NO se encontro. Va en la respuesta a proposito: un hueco
# declarado es informacion, y un hueco callado parece un cero.
NOT_FOUND = ["xNodes"]

# LA UNICA DE SUS CIFRAS QUE SI PODEMOS COMPROBAR, y sale redonda.
#
# El primer reajuste de dificultad cayo un 41,3%, que con bloques llegando
# rapido es al reves de lo que uno esperaria. La explicacion la da un dato
# NUESTRO: la ventana de ese reajuste empieza en el bloque 961.632, que es el
# de la separacion, y ese bloque lo medimos con nuestro propio nodo.
#
#   961.632   8 ago 2026 20:12 UTC   (medido aqui)
#   963.648   1 sep 2026 16:33 UTC   (lo dicen ellos)
#   -> 23,85 dias donde el objetivo son 14
#   -> 14 / 23,85 = 0,587, o sea una caida del 41,3%
#
# Clava el 41,3% que publican. Lo que demuestra no es que sean de fiar: es que
# la primera ventana de dificultad de su cadena nueva estaba llena de los
# veinte dias en que su cadena vieja estuvo casi parada. Nacio heredando la
# dificultad de su propio paron.
#
# Se recalcula en `_build_timeline` con la hora real del nodo, no se clava.
CHECK = {
    "retarget_height": 963648,
    "retarget_time_utc": "2026-09-01T16:33:00Z",
    "claimed_pct": -41.3,
    "target_days": 14,
}
