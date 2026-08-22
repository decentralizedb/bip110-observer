"""
/api/health no puede tardar mas que el corte del CDN.

Se calculaba dentro de la peticion, con `HEALTH_TIMEOUT_TOR` en 150 s y un
reintento. Cloudflare corta sobre los 100 y devuelve su propia pagina de
error en text/plain, que el navegador no sabe leer. Medido en produccion el
2026-08-22: 84 s en una llamada y un 524 en otra.

Y lo que lo hace grave: tarda mucho EXACTAMENTE cuando un nodo no responde,
o sea cuando hay algo que diagnosticar. El diagnostico se moria del mismo
mal que tenia que reportar.

Aqui se monta un nodo que tarda una eternidad y se comprueban las dos cosas
que importan: que la peticion vuelve rapido, y que el 503 sigue saliendo
cuando el nodo canonico no esta.
"""
import os
import sys
import time

os.environ["WARM_ON_START"] = "false"
os.environ["BTC_RPC_URL"] = "http://127.0.0.1:1/"
os.environ["BTC_RPC_URL_KNOTS"] = "http://127.0.0.1:2/"
os.environ["HEALTH_TTL"] = "45"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main  # noqa: E402

fallos = []


def ok(t, extra=""):
    print(f"ok     {t:52s} {extra}")


def falla(t, extra=""):
    print(f"FALLO  {t:52s} {extra}")
    fallos.append(t)


class NodoLento:
    """Un nodo que no contesta nunca dentro del plazo de la peticion."""

    def batch(self, *a, **k):
        time.sleep(30)
        raise RuntimeError("sin respuesta")

    def call(self, *a, **k):
        return self.batch()


main._rpc = lambda name: NodoLento()
main._active_url = lambda name: "http://127.0.0.1:1/"

cli = main.app.test_client()

# Primera llamada: no hay nada en cache, asi que responde "calculando" y
# lanza el hilo. Lo que NO puede hacer es esperar a que el nodo conteste.
t0 = time.time()
r1 = cli.get("/api/health")
d1 = time.time() - t0
if d1 < 5:
    ok("la primera llamada vuelve al instante", f"{d1:.2f}s")
else:
    falla("la primera llamada se queda esperando al nodo", f"{d1:.1f}s")

if r1.status_code == 503:
    ok("sin nodo canonico sigue devolviendo 503")
else:
    falla("el 503 se ha perdido", f"http={r1.status_code}")

if r1.is_json:
    ok("responde JSON, no la pagina de error de nadie")
else:
    falla("la respuesta no es JSON", r1.content_type)

# Y la segunda tampoco, con el hilo todavia dandole vueltas al nodo lento.
t0 = time.time()
r2 = cli.get("/api/health")
d2 = time.time() - t0
if d2 < 5:
    ok("la segunda llamada tampoco espera", f"{d2:.2f}s")
else:
    falla("la segunda llamada se queda esperando", f"{d2:.1f}s")

# El plazo del hilo de fondo va por encima de los 120 s que insiste Tor, y
# el del CDN esta muy por debajo: son dos plazos distintos y el endpoint no
# puede quedar atrapado entre los dos nunca mas.
if main.HEALTH_TIMEOUT_TOR > 120:
    ok("el hilo de fondo conserva su plazo largo", f"{main.HEALTH_TIMEOUT_TOR}s")
else:
    falla("el plazo por Tor ha bajado de 120 s", f"{main.HEALTH_TIMEOUT_TOR}s")

if "health" in main.TTL:
    ok("y /api/health tiene su propio TTL", f"{main.TTL['health']}s")
else:
    falla("/api/health no esta en la tabla de TTL")

print()
if fallos:
    print(f"{len(fallos)} fallos")
    sys.exit(1)
print("sin fallos")
