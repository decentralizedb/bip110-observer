#!/usr/bin/env python3
"""
Comprueba el diccionario de la interfaz.

Tres cosas, y las tres han fallado alguna vez:
  1. Las claves de `en` y `es` son exactamente las mismas.
  2. Toda clave usada en el codigo esta definida.
  3. La pagina no carga NADA de un tercero. Es la regla 2.3 del proyecto y
     conviene que la verifique una maquina, no la buena voluntad.

Uso: python3 test_i18n.py [fichero.html ...]
"""
import os
import re
import sys

DEFAULT = ["static/index.html", "static/methodology.html"]

# Se permiten enlaces salientes a estas fuentes: son citas, no recursos que
# el navegador cargue. Lo prohibido es src/href de recursos externos.
CITAS_OK = ("github.com/bitcoin/bips", "github.com/bitcoinknots",
            "bip110.dinerosinreglas.com", "bitcoinknots.org")


def dict_keys(blob, lang):
    m = re.search(r'^\s*%s\s*:\s*\{' % lang, blob, re.M)
    if not m:
        return None
    start = m.end()
    depth, i = 1, start
    while depth:
        if blob[i] == '{':
            depth += 1
        elif blob[i] == '}':
            depth -= 1
        i += 1
    body = blob[start:i]
    return set(re.findall(r'(?:^|[,{])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', body, re.M))


def check(path):
    src = open(path, encoding="utf-8").read()
    fails = []

    if "const DICT" in src:
        blob = src[src.index("const DICT"):]
        en, es = dict_keys(blob, "en"), dict_keys(blob, "es")
        if en is None or es is None:
            fails.append("no se encuentran los bloques en/es")
        else:
            if en - es:
                fails.append("claves solo en 'en': %s" % sorted(en - es))
            if es - en:
                fails.append("claves solo en 'es': %s" % sorted(es - en))
            used = set(re.findall(r't\("([A-Za-z][A-Za-z0-9_]*)"\s*[,)]', src))
            used |= set(re.findall(r'data-k="([A-Za-z0-9_]+)"', src))
            missing = sorted(u for u in used if u not in en)
            if missing:
                fails.append("usadas y no definidas: %s" % missing)
            print("  %s: %d claves en cada idioma" % (os.path.basename(path), len(en)))

    # Cifras clavadas en los textos. Son las que envejecen sin que nadie se
    # entere, porque nadie relee los textos buscando numeros. Todas estas
    # tienen que venir de la API e interpolarse con {marcador}.
    if "const DICT" in src:
        blob = src[src.index("const DICT"):]
        prohibidas = {
            "55": "umbral, usar {thr} desde /api/params",
            "1109": "umbral en bloques, usar {t}",
            "1,109": "umbral en bloques, usar {t}",
            "1.109": "umbral en bloques, usar {t}",
            "2016": "tamaño de periodo, usar {p}",
            "2,016": "tamaño de periodo, usar {p}",
            "2.016": "tamaño de periodo, usar {p}",
            "144": "bloques al dia, usar {bpd}",
            "961632": "altura, usar {n} desde /api/params",
            "961,632": "altura, usar {n} desde /api/params",
            "961.632": "altura, usar {n} desde /api/params",
        }
        for linea in blob.split("\n"):
            if ':"' not in linea:
                continue
            clave = linea.strip().split(":")[0].strip()
            for num, motivo in prohibidas.items():
                # Ojo con el lookahead: excluir '%' hacia que "55%" no se
                # detectase, que es justo la forma en que aparecen estas
                # cifras en los textos. La regla no servia para nada.
                if re.search(r'(?<![\d,.]){}(?![\d,.])'.format(re.escape(num)), linea):
                    fails.append(f"cifra clavada {num!r} en la clave {clave!r} ({motivo})")

    # Marcadores {x} de los textos que se pintan con data-k.
    #
    # Dos fallos distintos que la paridad de claves NO ve, porque las
    # claves estaban perfectas:
    #   a) el mismo nombre definido en dos conjuntos que luego se fusionan:
    #      uno pisa al otro y el panel llego a decir "10.080 pools
    #      identificados" cuando eran los bloques del historico.
    #   b) un marcador que nadie rellena: sale literalmente "{x}".
    def proveedores(texto):
        """Nombres que el codigo rellena, sea cual sea la forma de armarlos."""
        n = set()
        for m in re.finditer(r'const vars\s*=\s*', texto):
            trozo = texto[m.end():m.end() + 1200]
            n |= set(re.findall(r'(?:^|[,{]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', trozo, re.M))
        n |= set(re.findall(r'vars\.([A-Za-z_][A-Za-z0-9_]*)\s*=', texto))
        for fn in ("constVars", "coalitionVars"):
            m = re.search(r'function %s\(\)\s*\{' % fn, texto)
            if m:
                trozo = texto[m.end():texto.find("\n}", m.end())]
                n |= set(re.findall(r'(?:^|[,{]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', trozo, re.M))
        return n - {"return", "if", "const", "let"}

    if "const DICT" in src:
        disp = proveedores(src)
        dk = set(re.findall(r'data-k="([A-Za-z0-9_]+)"', src))
        blob = src[src.index("const DICT"):]
        vistos = set()
        for linea in blob.split("\n"):
            if ':"' not in linea:
                continue
            clave = linea.strip().split(":")[0].strip()
            if clave not in dk:
                continue
            for marc in set(re.findall(r'\{([a-zA-Z][a-zA-Z0-9_]*)\}', linea)):
                if marc not in disp and (clave, marc) not in vistos:
                    vistos.add((clave, marc))
                    fails.append(f"la clave {clave!r} usa {{{marc}}} y nadie lo rellena")

    # Nombres definidos a la vez en los dos conjuntos que se fusionan.
    def claves_de(texto, marca, fin_marca):
        i = texto.find(marca)
        if i < 0:
            return set()
        return set(re.findall(r'(?:^|[,{]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:',
                              texto[i:texto.find(fin_marca, i)], re.M))
    if "coalitionVars" in src:
        a = claves_de(src, "function constVars(){", "\n}")
        b = claves_de(src, "function coalitionVars(){", "\n}") - {"h", "P", "row", "first", "last"}
        c = claves_de(src, "const vars = Object.assign({", "}, constVars())")
        for x, y, donde in ((a, b, "constVars/coalitionVars"),
                            (c, b, "vars/coalitionVars")):
            choque = sorted((x & y) - {"return"})
            if choque:
                fails.append(f"marcadores definidos dos veces ({donde}): {choque}")

    # Recursos de terceros.
    #
    # Un enlace NO es un recurso. <a href="..."> lleva a otro sitio si el
    # visitante hace clic; <script src>, <img src> o <link href> descargan
    # algo sin preguntar. Lo prohibido por la regla 2.3 es lo segundo.
    # Meter los dos en el mismo saco daba falsos positivos con los enlaces
    # a las fuentes, que precisamente hay que poner.
    recursos = re.findall(r'\bsrc\s*=\s*"(https?://[^"]+)"', src)
    recursos += re.findall(r'<link\b[^>]*\bhref\s*=\s*"(https?://[^"]+)"', src)
    recursos += re.findall(r'@import\s+(?:url\()?["\']?(https?://[^"\')]+)', src)
    # El canonical es un enlace declarativo, no algo que se descargue.
    canon = re.findall(r'<link\b[^>]*rel="canonical"[^>]*href="([^"]+)"', src)
    externos = [u for u in recursos
                if u not in canon and not any(ok in u for ok in CITAS_OK)]
    if externos:
        fails.append("recursos externos que el navegador descargaria: %s"
                     % sorted(set(externos)))
    for pat in ("@import", "fonts.googleapis", "cdn.", "googleapis"):
        if pat in src:
            fails.append("referencia externa sospechosa: %s" % pat)

    return fails


def main():
    paths = sys.argv[1:] or [p for p in DEFAULT if os.path.exists(p)]
    bad = 0
    for p in paths:
        fails = check(p)
        for f in fails:
            print("  FALLO %s: %s" % (p, f))
            bad += 1
    if bad:
        print("%d fallos" % bad)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
