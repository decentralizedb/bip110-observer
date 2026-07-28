"""
Señalización del BIP-110 (Reduced Data Temporary Softfork).

Parámetros tomados literalmente de la sección ==Deployment== del texto
oficial del BIP en bitcoin/bips (bip-0110.mediawiki), versión 1.0.0
(Status: Complete, 2026-06-25).

  name:                  reduced_data
  bit:                   4
  starttime:             1764547200  (~1 diciembre 2025)
  timeout:               NO_TIMEOUT
  min_activation_height: 0
  max_activation_height: 965664      (~1 septiembre 2026)
  active_duration:       52416 bloques (~1 año)
  threshold:             1109/2016 (55%)

Ventanas relevantes (deviations from BIP9):
  - Señalización obligatoria: bloques 961632 .. 963647
      Durante esa ventana, los nodos que aplican el BIP-110 RECHAZAN
      como invalido cualquier bloque que no señalice el bit 4.
      Es AQUI donde se separan las cadenas, no cuando entran las reglas de datos.
  - LOCKED_IN forzado a mas tardar en el bloque 963648
  - ACTIVE (reglas de datos en vigor) en el bloque 965664
"""

BIP110 = {
    "name": "reduced_data",
    "bit": 4,
    "starttime": 1764547200,
    "max_activation_height": 965664,
    "active_duration": 52416,
    "threshold_num": 1109,
    "period": 2016,
    "mandatory_start": 961632,
    "mandatory_end": 963647,
    "forced_lockin": 963648,
    "activation_height": 965664,
}

VERSIONBITS_TOP_MASK = 0xE0000000
VERSIONBITS_TOP_BITS = 0x20000000


def signals_bit(version, bit=BIP110["bit"]):
    """
    Un bloque señaliza si los bits altos son los de versionbits (0x2)
    y el bit correspondiente esta a 1. Comprobar solo el bit sin validar
    la cabecera de versionbits produce falsos positivos.
    """
    if (version & VERSIONBITS_TOP_MASK) != VERSIONBITS_TOP_BITS:
        return False
    return bool(version & (1 << bit))


def period_bounds(height, period=BIP110["period"]):
    start = (height // period) * period
    return start, start + period - 1


def analyse(rpc, period_offset=0):
    """
    Analiza el periodo de retarget actual (o uno anterior con period_offset=-1, etc).
    Devuelve un dict con el recuento de señalización.
    """
    tip = rpc.get_block_count()
    p = BIP110["period"]
    start, end = period_bounds(tip)
    start += period_offset * p
    end += period_offset * p

    scan_end = min(end, tip)
    headers = rpc.headers_for_range(start, scan_end)

    signalling = [h for h in headers if signals_bit(h["version"])]
    scanned = len(headers)
    count = len(signalling)
    remaining = end - scan_end
    threshold = BIP110["threshold_num"]

    # ¿Sigue siendo alcanzable el umbral en este periodo?
    max_possible = count + remaining
    reachable = max_possible >= threshold

    return {
        "tip": tip,
        "period_start": start,
        "period_end": end,
        "blocks_scanned": scanned,
        "blocks_remaining": remaining,
        "signalling": count,
        "threshold": threshold,
        "threshold_pct": round(threshold / p * 100, 2),
        "pct_of_scanned": round(count / scanned * 100, 4) if scanned else 0.0,
        "pct_of_period": round(count / p * 100, 4),
        "max_possible": max_possible,
        "threshold_reachable": reachable,
        "signalling_heights": [h["height"] for h in signalling],
        "headers": headers,
    }


def milestones(tip):
    """Estado de las tres fechas que importan, calculado desde el tip."""
    def eta(target):
        d = target - tip
        return {
            "height": target,
            "blocks_away": d,
            "passed": d <= 0,
            # 10 min/bloque es la calibracion nominal, no una prediccion
            "approx_days": round(d * 10 / 60 / 24, 1) if d > 0 else 0,
        }

    return {
        "mandatory_signalling_start": eta(BIP110["mandatory_start"]),
        "forced_lockin": eta(BIP110["forced_lockin"]),
        "rules_active": eta(BIP110["activation_height"]),
        "in_mandatory_window": BIP110["mandatory_start"] <= tip <= BIP110["mandatory_end"],
    }


# ---------------------------------------------------------------------------
# Viabilidad de la cadena minoritaria
# ---------------------------------------------------------------------------

TARGET_SPACING = 600  # segundos por bloque de diseño


def minority_chain(share):
    """
    Dada una cuota de hashrate (0..1) que sigue la cadena BIP-110,
    calcula el ritmo de bloques y el tiempo hasta el primer reajuste.

    Fundamento: un soft fork NO toca el proof-of-work ni el algoritmo de
    ajuste. La cadena minoritaria hereda la dificultad de la principal,
    asi que el intervalo esperado escala con 1/share, y el primer retarget
    no llega hasta 2016 bloques despues.
    """
    if share <= 0:
        return {"share": 0.0, "viable": False, "interval_seconds": None,
                "interval_human": "sin bloques", "retarget_days": None,
                "retarget_human": "nunca", "blocks_per_day": 0.0}

    interval = TARGET_SPACING / share
    retarget_seconds = interval * BIP110["period"]

    return {
        "share": round(share, 6),
        "share_pct": round(share * 100, 2),
        "interval_seconds": round(interval),
        "interval_hours": round(interval / 3600, 2),
        "blocks_per_day": round(86400 / interval, 2),
        "retarget_seconds": round(retarget_seconds),
        "retarget_days": round(retarget_seconds / 86400, 1),
        "retarget_years": round(retarget_seconds / 86400 / 365.25, 2),
        # Comparativa: como queda la cadena mayoritaria al perder esa cuota
        "majority_interval_seconds": round(TARGET_SPACING / max(1e-9, 1 - share)),
        "viable": share >= 0.5,
    }


# ---------------------------------------------------------------------------
# Cuando llegarian los hitos en la cadena minoritaria
# ---------------------------------------------------------------------------

# El ajuste de dificultad no puede bajar de la cuarta parte en un solo
# periodo. Es consenso de Bitcoin de siempre, no algo del BIP-110.
MAX_RETARGET_DROP = 4

# Tope de periodos a simular. Con cuotas minusculas los hitos tardarian
# siglos: mejor decir "no llega" que imprimir un numero que nadie se cree.
MAX_PERIODS = 200


def milestone_projection(share):
    """
    Cuando alcanzaria la cadena BIP-110 sus propios hitos.

    POR QUE ESTO EXISTE. Los hitos del BIP-110 no son fechas, son ALTURAS,
    y se evaluan sobre la cadena del nodo que las mira, no sobre la cadena
    con mas trabajo. Verificado en el codigo de Bitcoin Knots, tag
    v29.3.knots20260508:

      src/deploymentstatus.h  DeploymentMustSignalAfter()
        return nHeight >= deployment.max_activation_height - (2 * nPeriod)
            && nHeight <  deployment.max_activation_height - nPeriod;

      src/versionbits.cpp
        } else if (... pindexPrev->nHeight + 1 >= max_activation_height - nPeriod) {
        if (pindexPrev->nHeight + 1 >= min_activation_height) {
        if (... pindexPrev->nHeight + 1 >= activation_height + active_duration) {

    El tiempo (MTP) solo interviene en DEFINED -> STARTED, que ya paso en
    diciembre de 2025, y en el timeout, que aqui es NO_TIMEOUT. Asi que si
    la cadena BIP-110 avanza despacio, sus reglas tardan mas en poder
    activarse EN ELLA. No es una opinion sobre el BIP: sale del codigo.

    ES UNA ESTIMACION, no un dato. Supuestos, los tres:
      1. La cuota se mantiene constante.
      2. Quien señaliza mina de verdad esa cadena. Señalizar es declarar
         intencion, no comprometerse.
      3. La dificultad baja como mucho a la cuarta parte por periodo.

    Y OJO CON QUE CUOTA SE PASA. La cadena minoritaria solo acepta bloques
    que señalicen, asi que su ritmo es el ritmo de BLOQUES SEÑALIZADOS, no
    la cuota total del pool que señaliza. Un pool con el 3,2% del minado
    que solo señaliza en la cuarta parte de sus bloques aporta el 0,8%, no
    el 3,2%. Por eso lo que entra aqui es signalling_share().
    """
    fork = BIP110["mandatory_start"]
    hitos = [
        ("forced_lockin", BIP110["forced_lockin"]),
        ("rules_active", BIP110["activation_height"]),
        ("rules_expire", BIP110["activation_height"] + BIP110["active_duration"]),
    ]

    def nominal(altura):
        """Lo que tardaria en una cadena que hace un bloque cada 10 minutos."""
        return (altura - fork) * TARGET_SPACING / 86400.0

    salida = {
        "share": round(share, 6),
        "share_pct": round(share * 100, 2),
        "fork_height": fork,
        "period": BIP110["period"],
        "max_retarget_drop": MAX_RETARGET_DROP,
        "milestones": [],
    }

    alcanzados = {}
    if share > 0:
        dificultad = 1.0   # relativa a la que hereda de la cadena principal
        altura, dias = fork, 0.0
        for _ in range(MAX_PERIODS):
            intervalo = TARGET_SPACING * dificultad / share      # segundos
            dias += BIP110["period"] * intervalo / 86400.0
            altura += BIP110["period"]
            for clave, objetivo in hitos:
                if altura >= objetivo and clave not in alcanzados:
                    alcanzados[clave] = dias
            if len(alcanzados) == len(hitos):
                break
            # El retarget persigue los 10 min por bloque. Con una cuota
            # 'share' el equilibrio esta justo en dificultad = share, y de
            # ahi no baja: seguir bajando daria bloques MAS rapidos que en
            # la cadena normal, que es imposible. El tope de la cuarta
            # parte por periodo es lo que impide llegar de golpe.
            #
            # Escrito como dificultad * share se acumulaba periodo tras
            # periodo y con el 55% daba que la cadena minoritaria llegaba
            # ANTES que la mayoritaria. Lo cazo la comprobacion de que
            # ningun hito puede tener slowdown menor que 1.
            dificultad = max(share, dificultad / MAX_RETARGET_DROP)

    for clave, objetivo in hitos:
        d = alcanzados.get(clave)
        salida["milestones"].append({
            "key": clave,
            "height": objetivo,
            "blocks_after_fork": objetivo - fork,
            "nominal_days": round(nominal(objetivo), 1),
            "nominal_years": round(nominal(objetivo) / 365.25, 2),
            "minority_days": round(d, 1) if d is not None else None,
            "minority_years": round(d / 365.25, 2) if d is not None else None,
            # Cuantas veces mas tarda. Es la cifra que cuenta la historia.
            "slowdown": (round(d / nominal(objetivo), 1)
                         if d is not None and nominal(objetivo) > 0 else None),
            "reachable": d is not None,
        })
    return salida


def signalling_share(analysis):
    """
    Estima la cuota de hashrate que seguiria la cadena BIP-110 a partir
    de la proporcion de bloques que señalizan en el periodo actual.

    Es una estimacion, no una medida: la señalizacion es una declaracion
    de intencion, no un compromiso. Un pool puede señalizar y luego no
    seguir la cadena, o al reves.
    """
    scanned = analysis.get("blocks_scanned", 0)
    if not scanned:
        return 0.0
    return analysis["signalling"] / scanned
