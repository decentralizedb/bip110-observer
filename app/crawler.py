"""
Crawler minimo del P2P de Bitcoin para recoger user agents.

LEE ESTO ANTES DE USAR LOS NUMEROS QUE PRODUCE:

Esto NO mide "cuantos nodos apoyan el BIP-110". No puede medirlo nadie.
Un nodo no publica sus reglas de consenso en ningun sitio. Lo unico
observable es el user agent, un campo de texto que el propio nodo
elige anunciar en el mensaje 'version'.

Los tres sesgos, en orden de gravedad:

1. AUTODECLARADO. El user agent se cambia con una linea de configuracion
   (uacomment / -uaappend). Un nodo Knots puede anunciarse como Core y
   al reves. No hay nada que verificar.

2. SOLO NODOS QUE ESCUCHAN. Solo se pueden alcanzar nodos con puerto
   abierto. La inmensa mayoria de nodos domesticos estan tras NAT sin
   redireccion y son invisibles para cualquier crawler. La muestra no es
   aleatoria: sobrerrepresenta VPS y servidores.

3. SYBIL TRIVIAL. Levantar mil nodos en un proveedor cloud cuesta cuatro
   duros. Cualquier bando puede inflar su recuento en una tarde y nadie
   puede distinguirlo desde fuera.

Y aunque los tres sesgos se resolvieran, seguiria sin medirse lo unico
que decide: cuanta actividad economica valida a traves de cada nodo.
Un nodo que verifica los cobros de un negocio pesa mas que mil nodos
ociosos, y desde fuera se ven exactamente iguales.

Trata la salida como una muestra sesgada, nunca como un recuento.
"""

import socket
import struct
import hashlib
import time
import random
import threading
from collections import deque

try:
    import socks  # PySocks, para salir por Tor
except ImportError:
    socks = None

MAGIC_MAINNET = bytes.fromhex("f9beb4d9")
PROTOCOL_VERSION = 70016
DEFAULT_PORT = 8333

# Bit de servicio que anuncian los nodos que aplican BIP-110.
#
# FUENTE PRIMARIA, verificada el 2026-07-27 en el codigo de Bitcoin Knots,
# tag v29.3.knots20260508 (la version que corre el nodo propio):
#
#   src/protocol.h
#     // NODE_REDUCED_DATA means the node enforces ReducedData rules as applicable
#     NODE_REDUCED_DATA = (1 << 27),
#
#   src/protocol.cpp
#     case NODE_REDUCED_DATA:    return "REDUCED_DATA?";
#
# Cuatro cosas que hay que tener presentes, todas comprobadas en ese codigo:
#
# 1. NO SALE DEL BIP. bip-0110.mediawiki (382 lineas, v1.0.0) no menciona
#    servicios P2P, NODE_ ni el bit 27. El BIP solo define el consenso.
#
# 2. ES UN BIT EXPERIMENTAL, y lo dice el propio protocol.h justo encima:
#    "Bits 24-31 are reserved for temporary experiments. [...] Remember that
#    service bits are just unauthenticated advertisements, so your code must
#    be robust against collisions and other cases where nodes may be
#    advertising a service they do not actually support."
#    O sea que la propia fuente advierte de que esto no es verificable y de
#    que puede colisionar. Los bits serios se asignan por el proceso BIP.
#
# 3. SE PUEDE DESACTIVAR. En src/init.cpp el bit entra por defecto
#    (g_local_services incluye NODE_REDUCED_DATA), pero se quita si el
#    usuario no consiente las reglas:
#      g_local_services = ServiceFlags(g_local_services & ~NODE_REDUCED_DATA);
#    Anunciarlo va atado a aplicar las reglas, no es independiente.
#
# 4. ES RECIENTE. No existe en v29.3.knots20260210 y si en
#    v29.3.knots20260416rc1. Por eso un nodo con el parche antiguo
#    (Knots:20260210+bip110-v0.4.1/UASF-BIP110:0.4) aplica BIP-110 y NO
#    anuncia el bit: solo lo dice en el user agent. Contarlo solo por el
#    bit lo dejaria fuera. De ahi la categoria "ua_only".
NODE_REDUCED_DATA = 1 << 27


def _checksum(payload):
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]


def _message(command, payload=b""):
    cmd = command.encode().ljust(12, b"\x00")
    return MAGIC_MAINNET + cmd + struct.pack("<I", len(payload)) + _checksum(payload) + payload


def _varint(n):
    if n < 0xFD:
        return struct.pack("<B", n)
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def _read_varint(data, off):
    b = data[off]
    if b < 0xFD:
        return b, off + 1
    if b == 0xFD:
        return struct.unpack("<H", data[off + 1:off + 3])[0], off + 3
    if b == 0xFE:
        return struct.unpack("<I", data[off + 1:off + 5])[0], off + 5
    return struct.unpack("<Q", data[off + 1:off + 9])[0], off + 9


def _version_payload():
    ts = int(time.time())
    payload = struct.pack("<iQq", PROTOCOL_VERSION, 0, ts)
    payload += struct.pack("<Q", 0) + b"\x00" * 16 + struct.pack(">H", DEFAULT_PORT)
    payload += struct.pack("<Q", 0) + b"\x00" * 16 + struct.pack(">H", DEFAULT_PORT)
    payload += struct.pack("<Q", random.getrandbits(64))
    ua = b"/bip110-observer:0.1/"
    payload += _varint(len(ua)) + ua
    payload += struct.pack("<i", 0)
    payload += b"\x00"  # no relay: no queremos que nos manden el mempool
    return payload


def network_of(host):
    """Red a la que pertenece una direccion, por su forma."""
    if host.endswith(".onion"):
        return "onion"
    if host.endswith(".i2p"):
        return "i2p"
    if ":" in host:
        return "ipv6"
    return "ipv4"


def _connect(host, port, use_tor, tor_host, tor_port, timeout):
    """
    Devuelve un socket ya conectado.

    Por Tor usamos SOCKS5 con rdns=True: la resolucion del nombre la hace
    el proxy, imprescindible para .onion y ademas evita filtrar por DNS.
    En claro usamos create_connection, que resuelve tanto IPv4 como IPv6.
    Con AF_INET fijo los nodos IPv6 eran inalcanzables.
    """
    if use_tor:
        if socks is None:
            raise RuntimeError("PySocks no instalado; no se puede salir por Tor")
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, tor_host, tor_port, rdns=True)
        s.settimeout(timeout)
        s.connect((host, port))
        return s
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(timeout)
    return s


def probe(host, port=DEFAULT_PORT, timeout=8, use_tor=False,
          tor_host="127.0.0.1", tor_port=9050, want_addrs=True):
    """
    Handshake minimo con un nodo. Devuelve dict con user_agent y, si se pide,
    direcciones de otros nodos obtenidas con getaddr.
    """
    result = {"host": host, "port": port, "ok": False, "network": network_of(host),
              "user_agent": None, "version": None, "height": None,
              "services": None, "bip110_service_bit": False, "addrs": []}
    s = None
    try:
        s = _connect(host, port, use_tor, tor_host, tor_port, timeout)
        s.sendall(_message("version", _version_payload()))

        buf = b""
        deadline = time.time() + timeout
        sent_getaddr = False

        while time.time() < deadline:
            try:
                chunk = s.recv(8192)
            except (socket.timeout, OSError):
                break
            if not chunk:
                break
            buf += chunk

            while len(buf) >= 24:
                magic, cmd, length, _cs = struct.unpack("<4s12sI4s", buf[:24])
                if magic != MAGIC_MAINNET or len(buf) < 24 + length:
                    break
                payload = buf[24:24 + length]
                buf = buf[24 + length:]
                command = cmd.rstrip(b"\x00").decode("ascii", "ignore")

                if command == "version":
                    try:
                        # version(4) services(8) timestamp(8) addr_recv(26)
                        # addr_from(26) nonce(8) -> user agent
                        services = struct.unpack("<Q", payload[4:12])[0]
                        off = 4 + 8 + 8 + 26 + 26 + 8
                        ua_len, off = _read_varint(payload, off)
                        ua = payload[off:off + ua_len].decode("ascii", "ignore")
                        off += ua_len
                        height = struct.unpack("<i", payload[off:off + 4])[0]
                        result["user_agent"] = ua
                        result["version"] = struct.unpack("<i", payload[:4])[0]
                        result["height"] = height
                        result["services"] = services
                        result["bip110_service_bit"] = bool(services & NODE_REDUCED_DATA)
                        result["ok"] = True
                    except (struct.error, IndexError):
                        pass
                    s.sendall(_message("verack"))

                elif command == "verack":
                    if want_addrs and not sent_getaddr:
                        s.sendall(_message("getaddr"))
                        sent_getaddr = True
                    elif not want_addrs:
                        return result

                elif command == "ping":
                    s.sendall(_message("pong", payload[:8]))

                elif command in ("addr", "addrv2"):
                    result["addrs"].extend(_parse_addrs(payload, command))
                    if result["ok"]:
                        return result

        return result
    except Exception as e:
        result["error"] = str(e)
        return result
    finally:
        if s is not None:
            try:
                s.close()
            except OSError:
                pass


def _parse_addrs(payload, command):
    out = []
    try:
        count, off = _read_varint(payload, 0)
        count = min(count, 1000)
        for _ in range(count):
            if command == "addr":
                off += 4 + 8  # time + services
                ip_bytes = payload[off:off + 16]; off += 16
                port = struct.unpack(">H", payload[off:off + 2])[0]; off += 2
                if ip_bytes[:12] == b"\x00" * 10 + b"\xff\xff":
                    ip = ".".join(str(b) for b in ip_bytes[12:16])
                    out.append((ip, port))
            else:  # addrv2
                off += 4
                _svc, off = _read_varint(payload, off)
                net = payload[off]; off += 1
                alen, off = _read_varint(payload, off)
                addr = payload[off:off + alen]; off += alen
                port = struct.unpack(">H", payload[off:off + 2])[0]; off += 2
                if net == 1 and alen == 4:
                    out.append((".".join(str(b) for b in addr), port))
                elif net == 4 and alen == 32:
                    import base64
                    ver = bytes([3])
                    chk = hashlib.sha3_256(b".onion checksum" + addr + ver).digest()[:2]
                    onion = base64.b32encode(addr + chk + ver).decode().lower() + ".onion"
                    out.append((onion, port))
    except (struct.error, IndexError):
        pass
    return out


def crawl(seeds, max_nodes=300, threads=16, use_tor=False,
          tor_host="127.0.0.1", tor_port=9050, timeout=8, include_onion=False,
          onion_timeout=None, budget_seconds=180):
    """
    Recorre la red partiendo de una lista de semillas (host, port).
    Devuelve lista de resultados de probe().

    Redes: IPv4 e IPv6 se alcanzan directamente o por Tor; .onion solo por
    Tor y solo si include_onion. Las direcciones .i2p se descartan siempre:
    hablar con ellas exige un router I2P con proxy SAM, que este contenedor
    no lleva. Contarlas como sondeables daria una muestra falsa.

    Los hilos esperan mientras haya sondeos en vuelo en lugar de salir en
    cuanto la cola esta vacia. Sin eso, con pocas semillas casi todos los
    hilos terminaban en el arranque, antes del primer getaddr, y por Tor
    (donde cada handshake tarda segundos) el recorrido moria siempre.
    """
    if onion_timeout is None:
        onion_timeout = timeout * 3

    def usable(addr):
        host, port = addr
        if not port or port < 1 or port > 65535:
            return False
        net = network_of(host)
        if net == "i2p":
            return False
        if net == "onion":
            return include_onion
        return True

    queue = deque(a for a in seeds if usable(a))
    seen = set(queue)
    results = []
    cv = threading.Condition()
    inflight = 0
    finished = False
    deadline = time.time() + budget_seconds

    def worker():
        nonlocal inflight, finished
        while True:
            with cv:
                while True:
                    if finished or len(results) >= max_nodes or time.time() >= deadline:
                        finished = True
                        cv.notify_all()
                        return
                    if queue:
                        host, port = queue.popleft()
                        inflight += 1
                        break
                    if inflight == 0:
                        # Cola vacia y nadie sondeando: no llegara nada mas.
                        finished = True
                        cv.notify_all()
                        return
                    cv.wait(timeout=1.0)

            is_onion = host.endswith(".onion")
            r = probe(host, port,
                      timeout=onion_timeout if is_onion else timeout,
                      use_tor=use_tor or is_onion,
                      tor_host=tor_host, tor_port=tor_port)

            with cv:
                inflight -= 1
                if r.get("ok"):
                    results.append(r)
                for a in r.get("addrs", []):
                    if a in seen or len(seen) >= max_nodes * 12:
                        continue
                    if not usable(a):
                        continue
                    seen.add(a)
                    queue.append(a)
                cv.notify_all()

    ts = [threading.Thread(target=worker, daemon=True) for _ in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=budget_seconds + 30)

    return results


def classify(user_agent):
    """Clasificacion gruesa por user agent. Recordatorio: es autodeclarado."""
    if not user_agent:
        return "Desconocido"
    ua = user_agent.lower()
    if "knots" in ua:
        return "Knots"
    if "satoshi" in ua:
        return "Core"
    return "Otro"


def classify_rules(result):
    """
    Que dice el nodo sobre BIP-110. Devuelve una clave estable (no texto
    traducido: la interfaz se encarga de eso). Cuatro cosas distintas que
    no se mezclan:

      "declares"          anuncia el bit de servicio 27
      "ua_only"           no anuncia el bit pero pone bip110 en el texto
      "knots_undeclared"  corre Knots y no declara nada
      "undeclared"        el resto

    Correr Knots NO es aplicar BIP-110: depende de la version y de la
    configuracion. Contar nodos Knots como apoyo al BIP-110 es el error mas
    extendido en la cobertura del tema, y aqui se separan a proposito.

    Y esto sigue siendo autodeclarado. El bit se pone con una linea de
    configuracion igual que el user agent. Es mejor señal, no es una señal
    de otra naturaleza: no hay forma de verificar desde fuera que un nodo
    vaya a aplicar unas reglas de consenso.
    """
    ua = (result.get("user_agent") or "").lower()
    if result.get("bip110_service_bit"):
        return "declares"
    if "bip110" in ua or "bip-110" in ua:
        return "ua_only"
    if "knots" in ua:
        return "knots_undeclared"
    return "undeclared"


def summarise(results, networks_probed=None, networks_skipped=None):
    counts = {}
    by_network = {}
    by_rules = {}
    for r in results:
        c = classify(r.get("user_agent"))
        counts[c] = counts.get(c, 0) + 1
        n = r.get("network") or "desconocida"
        by_network[n] = by_network.get(n, 0) + 1
        k = classify_rules(r)
        by_rules[k] = by_rules.get(k, 0) + 1
    total = sum(counts.values())
    return {
        "total_reachable_sampled": total,
        "by_client": counts,
        "by_network": by_network,
        "by_rules": by_rules,
        "pct_rules": ({k: round(v / total * 100, 2) for k, v in by_rules.items()}
                      if total else {}),
        "caveat_rules": ("El bit de servicio 27 lo define Bitcoin Knots, no el "
                         "BIP-110, y no esta registrado en ningun BIP. Se pone "
                         "con una linea de configuracion, asi que sigue siendo "
                         "autodeclarado. Correr Knots no implica aplicar "
                         "BIP-110."),
        "networks_probed": sorted(networks_probed or by_network.keys()),
        "networks_skipped": sorted(networks_skipped or []),
        "pct": {k: round(v / total * 100, 2) for k, v in counts.items()} if total else {},
        "caveat": ("Muestra sesgada de nodos alcanzables. El user agent es "
                   "autodeclarado y trivialmente falsificable. No mide reglas "
                   "de consenso ni peso economico."),
        "caveat_networks": ("La muestra solo cubre las redes sondeadas. i2p y "
                            "cjdns quedan fuera: alcanzarlas exige un router "
                            "propio de esas redes, que este panel no ejecuta."),
    }
