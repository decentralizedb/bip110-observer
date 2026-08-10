"""Ejecuta audit.py con el .env del repositorio ya cargado.

audit.py hace `import main`, asi que necesita las variables del nodo en el
entorno. Sin ellas todas las comprobaciones fallan por conexion rechazada y
el informe parece una averia del panel cuando es una del banco de pruebas.
"""
import os
import runpy

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

for linea in open(os.path.join(RAIZ, ".env")):
    linea = linea.strip()
    if linea and not linea.startswith("#") and "=" in linea:
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

os.environ["WARM_ON_START"] = "false"
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit.py"),
               run_name="__main__")
