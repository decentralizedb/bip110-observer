"""
Cliente JSON-RPC para Bitcoin Core.

Soporta:
  - clearnet (http://host:8332)
  - Tor (http://xxxxx.onion:8332) via SOCKS5h, resolviendo el .onion en el proxy
  - batching (imprescindible: escanear 2016 bloques uno a uno es lentísimo)
"""

import os
import json
import itertools
import requests


class RPCError(Exception):
    pass


class BitcoinRPC:
    def __init__(self, url=None, user=None, password=None,
                 tor_proxy=None, timeout=120):
        self.url = url or os.environ.get("BTC_RPC_URL", "http://127.0.0.1:8332")
        self.user = user if user is not None else os.environ.get("BTC_RPC_USER", "")
        self.password = password if password is not None else os.environ.get("BTC_RPC_PASSWORD", "")
        self.timeout = timeout
        self._id = itertools.count(1)

        self.session = requests.Session()
        self.session.auth = (self.user, self.password)
        self.session.headers.update({"Content-Type": "application/json"})

        # Si el nodo es .onion forzamos SOCKS5h para que la resolución
        # del hostname la haga Tor y no el contenedor.
        is_onion = ".onion" in self.url
        proxy = tor_proxy or os.environ.get("TOR_SOCKS", "socks5h://127.0.0.1:9050")
        if is_onion:
            self.session.proxies = {"http": proxy, "https": proxy}
            self.timeout = max(self.timeout, 180)  # Tor es lento

        self.is_onion = is_onion

    def call(self, method, *params):
        payload = {
            "jsonrpc": "1.0",
            "id": next(self._id),
            "method": method,
            "params": list(params),
        }
        r = self.session.post(self.url, data=json.dumps(payload), timeout=self.timeout)
        # Bitcoin Core responde HTTP 500 a un error de RPC y pone el motivo
        # en el cuerpo. Con raise_for_status() delante se tiraba justo esa
        # parte y quedaba un "500 Server Error" que no dice nada: asi se
        # perdio un dia buscando por que fallaba getnodeaddresses, cuando el
        # nodo estaba contestando "expected number, got array".
        if r.status_code >= 400:
            try:
                err = r.json().get("error")
            except ValueError:
                err = None
            if err:
                raise RPCError(f"{method}: {err}")
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise RPCError(f"{method}: {data['error']}")
        return data["result"]

    def batch(self, calls, _depth=0):
        """
        calls: lista de tuplas (method, [params...])
        Devuelve lista de resultados en el mismo orden.

        Si la respuesta se corta a media descarga partimos el lote en dos y
        reintentamos. Pasa con getblock: un bloque actual son unos 250 KB de
        JSON aunque uses verbosity=1, asi que un lote grande pide decenas de
        megabytes y por Tor la conexion no siempre aguanta.
        """
        if not calls:
            return []
        payload = []
        for method, params in calls:
            payload.append({
                "jsonrpc": "1.0",
                "id": next(self._id),
                "method": method,
                "params": list(params),
            })
        try:
            r = self.session.post(self.url, data=json.dumps(payload), timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except (requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                ValueError) as e:
            if len(calls) > 1 and _depth < 8:
                mid = len(calls) // 2
                return (self.batch(calls[:mid], _depth + 1) +
                        self.batch(calls[mid:], _depth + 1))
            raise RPCError(f"batch fallido ({len(calls)} llamadas): {e}") from e

        # El batch puede volver desordenado: reordenamos por id
        by_id = {item["id"]: item for item in data}
        out = []
        for req in payload:
            item = by_id.get(req["id"])
            if item is None:
                raise RPCError(f"Respuesta batch incompleta para id {req['id']}")
            if item.get("error"):
                raise RPCError(f"{req['method']}: {item['error']}")
            out.append(item["result"])
        return out

    # --- helpers ---

    def get_block_count(self):
        return self.call("getblockcount")

    def get_blockchain_info(self):
        return self.call("getblockchaininfo")

    def get_network_info(self):
        return self.call("getnetworkinfo")

    def get_peer_info(self):
        return self.call("getpeerinfo")

    def get_node_addresses(self, count=500, network=None):
        """
        Libreta de direcciones del propio nodo (addrman), no sus peers.

        Es la diferencia entre "con quien esta hablando ahora" y "a quien
        conoce". Con un nodo en onlynet=onion lo primero son tres o cuatro
        direcciones y lo segundo son miles, muchas IPv4 alcanzables en claro.

        'count' se acota a proposito: con 0 devuelve TODO lo que conoce, que
        por un servicio oculto son megabytes de JSON para el mismo fin.

        El argumento 'network' existe desde Bitcoin Core v22. Si el nodo es
        mas viejo, la llamada falla y se reintenta sin filtrar.
        """
        # OJO: call() es variadico. Pasarle una lista manda [[500]] al nodo,
        # que espera un numero, y lo unico que llega de vuelta es un HTTP 500.
        #
        # Si falla con 'network' NO se reintenta sin el: devolveria la lista
        # general haciendose pasar por la de esa red, y quien la pidio no se
        # enteraria. Que falle y se vea.
        if network:
            return self.call("getnodeaddresses", count, network)
        return self.call("getnodeaddresses", count)

    def headers_for_range(self, start_height, end_height, chunk=250):
        """
        Devuelve [{height, hash, version, time}] para [start, end] inclusive.
        Usa batching en dos fases: getblockhash -> getblockheader.
        """
        out = []
        heights = list(range(start_height, end_height + 1))
        for i in range(0, len(heights), chunk):
            hs = heights[i:i + chunk]
            hashes = self.batch([("getblockhash", [h]) for h in hs])
            headers = self.batch([("getblockheader", [bh, True]) for bh in hashes])
            for h, bh, hdr in zip(hs, hashes, headers):
                out.append({
                    "height": h,
                    "hash": bh,
                    "version": hdr["version"],
                    "time": hdr["time"],
                })
        return out
