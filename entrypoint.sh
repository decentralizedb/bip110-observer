#!/bin/sh
set -e

# Arrancamos Tor solo si hace falta.
#
# Hay que mirar las CUATRO direcciones, no solo BTC_RPC_URL. Con el respaldo
# clearnet/Tor la .onion vive normalmente en BTC_RPC_TOR_URL, asi que mirar
# solo la primera dejaba Tor sin arrancar y todo fallaba con "Connection
# refused" contra el SOCKS del 9050, que es un mensaje que no apunta a nada.
NEEDS_TOR=0
for u in "$BTC_RPC_URL" "$BTC_RPC_TOR_URL" "$BTC_RPC_URL_KNOTS" "$BTC_RPC_TOR_URL_KNOTS"; do
  case "$u" in *.onion*) NEEDS_TOR=1 ;; esac
done
[ "$CRAWL_VIA_TOR" = "true" ] && NEEDS_TOR=1

if [ "$NEEDS_TOR" = "1" ]; then
  echo "[bip110] Arrancando Tor..."
  tor --SocksPort 9050 --Log "notice stdout" --RunAsDaemon 1

  # Esperamos a que el SOCKS este listo antes de servir peticiones.
  # Sondeamos el propio nodo, no check.torproject.org: evita depender de un
  # tercero y ademas comprueba lo que de verdad importa, que el servicio
  # oculto responde. Si no hay .onion configurada, basta con que el puerto
  # SOCKS acepte conexiones.
  for i in $(seq 1 60); do
    ONION_URL=""
    for u in "$BTC_RPC_TOR_URL" "$BTC_RPC_URL" "$BTC_RPC_TOR_URL_KNOTS" "$BTC_RPC_URL_KNOTS"; do
      case "$u" in *.onion*) ONION_URL="$u"; break ;; esac
    done
    if [ -n "$ONION_URL" ]; then
      if curl -s --socks5-hostname 127.0.0.1:9050 -m 10 -o /dev/null \
           --user "$BTC_RPC_USER:$BTC_RPC_PASSWORD" \
           --data '{"jsonrpc":"1.0","id":"boot","method":"getblockcount","params":[]}' \
           "$ONION_URL" 2>/dev/null; then
        echo "[bip110] Tor listo, el nodo responde por el servicio oculto."; break
      fi
    else
      if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(3); sys.exit(s.connect_ex(('127.0.0.1',9050)))" 2>/dev/null; then
        echo "[bip110] SOCKS de Tor escuchando."; break
      fi
    fi
    sleep 2
  done
fi

# UN solo worker, a proposito.
#
# La cache y la eleccion de direccion del nodo viven en memoria del
# proceso, asi que con dos workers cada uno tiene las suyas: el mismo
# escaneo caro se haria dos veces contra el nodo, y por Tor eso son
# minutos duplicados. El trabajo es de espera de red, no de CPU, asi que
# los hilos sobran para servir visitas.
exec gunicorn --bind 0.0.0.0:8110 --workers 1 --threads 16 --timeout 900 main:app
