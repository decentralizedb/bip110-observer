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

# Rutas contra ESTE fichero, no contra el directorio desde el que se llame.
# Con rutas relativas, ejecutarlo desde fuera de app/ no encontraba ningun
# fichero, la lista quedaba vacia y el bucle no daba ni una vuelta: imprimia
# "OK" sin haber mirado nada. Una herramienta que aprueba en vacio es peor
# que no tenerla, porque da por revisado lo que nadie ha revisado.
AQUI = os.path.dirname(os.path.abspath(__file__))
DEFAULT = [os.path.join(AQUI, "static", "index.html"),
           os.path.join(AQUI, "static", "methodology.html")]

# Se permiten enlaces salientes a estas fuentes: son citas, no recursos que
# el navegador cargue. Lo prohibido es src/href de recursos externos.
CITAS_OK = ("github.com/bitcoin/bips", "github.com/bitcoinknots",
            "bip110.dinerosinreglas.com", "bitcoinknots.org")


def sin_cadenas(texto):
    """El mismo texto, con el contenido de las cadenas puesto en blanco.

    Contar llaves sobre el texto crudo se rompe en cuanto una cita de codigo
    lleva { } dentro de una cadena. Paso de verdad: se anadio una cita que
    empieza por '}' y el contador dio por cerrado el bloque 'en' justo ahi,
    asi que el test leyo 44 claves en vez de 78 y acuso de faltar a la mitad
    del diccionario. El fallo era del lector, no del texto.

    Se conserva la longitud para que las posiciones sigan valiendo, y se
    respetan las comillas escapadas.
    """
    out, dentro, i = [], False, 0
    while i < len(texto):
        c = texto[i]
        if dentro:
            if c == "\\" and i + 1 < len(texto):
                out.append("  ")
                i += 2
                continue
            out.append(c if c == '"' else " ")
            if c == '"':
                dentro = False
        else:
            out.append(c)
            if c == '"':
                dentro = True
        i += 1
    return "".join(out)


def sin_comentarios(texto):
    """Quita comentarios de bloque y de linea, conservando los saltos.

    Los comentarios de este proyecto citan a proposito las cifras que la
    regla prohibe ("el 55%, los 2016 bloques"), asi que mirarlos daria una
    falsa alarma en cada explicacion de la propia regla.
    """
    texto = re.sub(r'/\*.*?\*/', lambda m: "\n" * m.group(0).count("\n"),
                   texto, flags=re.S)
    return re.sub(r'(?<!:)//[^\n]*', "", texto)


def impresiones_de(texto):
    """[(trozo, linea)] donde una cifra literal se esta pintando.

    Dos formas, y solo dos: pegada a un '%' y suelta entre dos etiquetas.
    Las dos son inequivocas, y ninguna necesita saber donde empieza y acaba
    una cadena.

    El primer intento si parseaba comillas, y no valia: este fichero mezcla
    HTML, CSS y JS, la prosa esta llena de apostrofes, y cualquier comilla
    descuadrada arrastraba el resto del fichero dentro de una cadena
    imaginaria. Daba dos falsas alarmas seguidas apuntando a lineas que no
    tenian ninguna cifra. Mas estrecho y fiable le gana a mas amplio y
    ruidoso: una comprobacion con falsas alarmas se acaba ignorando.
    """
    salida = []
    for n, linea in enumerate(texto.split("\n"), 1):
        for m in re.finditer(r'([\d,.]+)\s*%', linea):
            salida.append((m.group(1), n, linea))
        for m in re.finditer(r'>\s*([\d,.]+)\s*<', linea):
            salida.append((m.group(1), n, linea))
    return salida


def dict_keys(blob, lang):
    blob = sin_cadenas(blob)
    m = re.search(r'^\s*%s\s*:\s*\{' % lang, blob, re.M)
    if not m:
        return None
    start = m.end()
    depth, i = 1, start
    while depth and i < len(blob):
        if blob[i] == '{':
            depth += 1
        elif blob[i] == '}':
            depth -= 1
        i += 1
    if depth:
        return None
    body = blob[start:i]
    return set(re.findall(r'(?:^|[,{])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', body, re.M))


def bloque_de(blob, lang):
    """El trozo del diccionario de un idioma, con sus valores."""
    ini = blob.find("\n%s:{" % lang)
    if ini < 0:
        ini = blob.find("\n%s: {" % lang)
    if ini < 0:
        return None
    fin = blob.find("\n},", ini)
    return blob[ini:fin if fin > 0 else len(blob)]


def check(path):
    src = open(path, encoding="utf-8").read()
    fails = []

    # UNA FUNCION DECLARADA DOS VECES NO DA ERROR: LA SEGUNDA PISA A LA
    # PRIMERA EN SILENCIO.
    #
    # El 2026-08-08 habia dos `hace()` en index.html. La segunda, escrita
    # meses despues para otra cosa, sustituyo a la original sin que fallara
    # nada: se perdio el tramo de segundos y el singular, y la cabecera
    # llevaba quien sabe cuanto diciendo "1 minutes". En un fichero de dos
    # mil lineas con el JS dentro, esto no se ve leyendo.
    nombres = re.findall(r"^function\s+([A-Za-z_$][\w$]*)\s*\(", src, re.M)
    repes = sorted({n for n in nombres if nombres.count(n) > 1})
    for n in repes:
        fails.append("funcion declarada %d veces: %s()" % (nombres.count(n), n))

    # UN HITO, UN NOMBRE.
    #
    # Las mismas dos alturas se llamaban de dos maneras segun la seccion: la
    # cronologia usaba nombres llanos y el recorrido los nombres del
    # protocolo (LOCKED_IN, ACTIVE). Para el lector no son el mismo sitio, y
    # entonces el panel parece estar hablando de cuatro momentos y no de dos.
    # Si algun dia se cambia uno, este par tiene que cambiarse entero.
    # Se comparan POR IDIOMA, en el mismo orden en que aparecen los dos
    # diccionarios. La primera version buscaba solo la primera aparicion, o
    # sea siempre la inglesa, y rompiendo el texto castellano no fallaba.
    for a, b in (("ms2", "strMs2"), ("ms3", "strMs3")):
        v1 = re.findall(r'\b%s:"((?:[^"\\]|\\.)*)"' % a, src)
        v2 = re.findall(r'\b%s:"((?:[^"\\]|\\.)*)"' % b, src)
        for i, (x, y) in enumerate(zip(v1, v2)):
            if x != y:
                fails.append("la misma altura con dos nombres (%s): %s=%r y %s=%r"
                             % ("en" if i == 0 else "es", a, x, b, y))

    # Un numero con separador de miles dentro de un comando no se puede
    # pegar: "getblockhash 961,632" no funciona. Lo que se imprime para
    # ejecutar va sin formatear.
    for m in re.finditer(r"(bitcoin-cli\s+\w+\s+)\{(\w+)\}", src):
        if m.group(2) in ("h", "n", "tip", "height"):
            fails.append("comando con un marcador que se imprime formateado: "
                         "%s{%s}" % (m.group(1), m.group(2)))

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
            # Mismos marcadores en los dos idiomas.
            #
            # La paridad de CLAVES no basta y el hueco es facil de caer:
            # basta con retocar un texto en un idioma y olvidar el otro. Las
            # claves siguen cuadrando, asi que todo pasa, y en pantalla queda
            # o un texto viejo o un "{cap}" sin rellenar. Los marcadores son
            # lo unico comprobable de forma automatica: si una version dice
            # {normal} y la otra no, una de las dos esta sin actualizar.
            vals = {}
            for lang in ("en", "es"):
                vals[lang] = dict(re.findall(
                    r'\n\s*([A-Za-z][A-Za-z0-9_]*)\s*:\s*"((?:[^"\\]|\\.)*)"',
                    bloque_de(blob, lang) or ""))
            for k in sorted(en & es):
                m_en = set(re.findall(r"\{([a-zA-Z][a-zA-Z0-9_]*)\}", vals["en"].get(k, "")))
                m_es = set(re.findall(r"\{([a-zA-Z][a-zA-Z0-9_]*)\}", vals["es"].get(k, "")))
                if m_en != m_es:
                    fails.append(
                        "la clave %r no lleva los mismos marcadores en los dos "
                        "idiomas: en=%s es=%s (un idioma se quedo sin actualizar)"
                        % (k, sorted(m_en), sorted(m_es)))
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

        # Y lo mismo FUERA del diccionario. Esta parte faltaba, y por el
        # hueco se colo un "55%" escrito a mano en el codigo que dibuja la
        # barra del umbral: el diccionario estaba limpio y la pantalla no.
        #
        # Solo se miran las cadenas, que es lo unico que llega a pantalla.
        # Un `|| 2016` de respaldo en una cuenta no es una cifra clavada en
        # un texto, y tratarlo como tal llenaria esto de falsas alarmas
        # hasta que alguien lo apagara.
        fin = src.find("\n};", src.index("const DICT"))
        fuera = src[:src.index("const DICT")] + (src[fin:] if fin > 0 else "")
        for cifra, linea_n, linea in impresiones_de(sin_comentarios(fuera)):
            motivo = prohibidas.get(cifra)
            if motivo:
                fails.append("cifra clavada %r fuera del diccionario, "
                             "linea %d: %r (%s)"
                             % (cifra, linea_n, linea.strip()[:70], motivo))

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
