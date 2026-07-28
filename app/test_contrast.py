#!/usr/bin/env python3
"""
Contraste de los dos temas.

Lee los colores directamente de index.html, asi que no hay dos listas que
puedan desincronizarse: si alguien cambia la paleta y rompe la
legibilidad, esto falla.

Se mide sobre TODOS los fondos donde el texto aparece de verdad, no solo
sobre el panel principal. La primera version solo comprobaba el panel y
daba todo por bueno mientras el texto tenue sobre las tarjetas mas claras
se quedaba en 4,36, por debajo del minimo. El fondo mas claro es el que
manda, no el mas comodo de medir.

Los umbrales:
  4.5  minimo AA para texto normal
  6.0  el que se exige aqui a la prosa, porque AA es el suelo y este panel
       se lee entero, no de un vistazo

Uso: python3 test_contrast.py
"""
import re
import sys

FICHERO = "static/index.html"
MIN_AA = 4.5
MIN_PROSA = 6.0


def lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + .05) / (lo + .05)


def paleta(src, selector):
    """Variables de color de un tema, leidas del propio CSS."""
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\}", src, re.S)
    if not m:
        return {}
    return {k: v for k, v in re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})", m.group(1))}


def main():
    src = open(FICHERO, encoding="utf-8").read()
    temas = {
        "oscuro": paleta(src, ":root"),
        "claro": paleta(src, ':root[data-theme="light"]'),
    }

    # Cada texto contra CADA fondo sobre el que puede aparecer.
    fondos = ["bg", "panel", "panel2", "panel3"]
    casos = [
        ("texto principal", "txt", MIN_PROSA),
        ("texto secundario", "txt2", MIN_PROSA),
        ("texto tenue (prosa)", "dim", MIN_PROSA),
        ("texto tenue (etiquetas)", "dim2", MIN_AA),
        ("naranja: muestra sesgada", "orange-t", MIN_AA),
        ("verde: dato verificable", "green", MIN_AA),
        ("azul: estimacion", "blue", MIN_AA),
        ("rojo: error", "red", MIN_AA),
    ]

    fallos = 0
    for nombre, p in temas.items():
        if not p:
            print(f"  FALLO: no se encuentra la paleta del tema {nombre}")
            return 1
        print(f"=== tema {nombre} ===")
        for etiqueta, clave, minimo in casos:
            if clave not in p:
                print(f"  FALLO   falta la variable --{clave}")
                fallos += 1
                continue
            peor, peor_fondo = 99.0, ""
            for f in fondos:
                if f not in p:
                    continue
                r = ratio(p[clave], p[f])
                if r < peor:
                    peor, peor_fondo = r, f
            marca = "ok    " if peor >= minimo else "FALLO "
            if peor < minimo:
                fallos += 1
            print(f"  {marca}  {etiqueta:28s} {peor:5.2f}  (peor caso: sobre --{peor_fondo}, "
                  f"minimo {minimo})")
        print()

    print("sin fallos" if not fallos else f"{fallos} fallos de contraste")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
