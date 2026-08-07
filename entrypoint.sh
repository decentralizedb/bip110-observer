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

# Primera .onion de las que se le pasen, o nada. Sirve para quedarse con la
# direccion de cada nodo sin repetir el case en cuatro sitios.
primera_onion() {
  for u in "$@"; do
    case "$u" in *.onion*) echo "$u"; return 0 ;; esac
  done
}

# Sondea UN nodo por su servicio oculto.
#   $1 nombre para el registro   $2 url   $3 usuario   $4 clave   $5 intentos
#
# Mide ALCANCE, no autenticacion: curl considera exito cualquier respuesta
# HTTP, asi que un 401 por credenciales equivocadas tambien cuenta como
# "se llega". Es lo que queremos aqui; de las credenciales ya avisa
# /api/health con el nodo en marcha.
sondear() {
  case "$2" in *.onion*) ;; *) return 0 ;; esac
  n=0
  while [ "$n" -lt "$5" ]; do
    if curl -s --socks5-hostname 127.0.0.1:9050 -m 10 -o /dev/null \
         --user "$3:$4" \
         --data '{"jsonrpc":"1.0","id":"boot","method":"getblockcount","params":[]}' \
         "$2" 2>/dev/null; then
      echo "[bip110] $1: responde por el servicio oculto."
      return 0
    fi
    n=$((n + 1))
    sleep 2
  done
  echo "[bip110] AVISO: $1 NO responde por el servicio oculto ($5 intentos)."
  return 1
}

if [ "$NEEDS_TOR" = "1" ]; then
  echo "[bip110] Arrancando Tor..."

  # Tor en segundo plano, NO demonizado.
  #
  # Antes se le pedian dos cosas incompatibles a la vez: escribir en la
  # salida estandar y demonizarse, que es precisamente cerrarla. Tor lo
  # avisaba ("Can't log to stdout with RunAsDaemon set; skipping stdout") y
  # se tiraba su propio registro. Resultado: el 2026-08-07 el panel estuvo
  # media hora sin ver el nodo secundario y hubo que deducir el motivo a
  # base de curl, porque el fichero que lo explicaba no existia. Un fallo
  # de red en un servicio oculto se diagnostica con el registro de Tor o no
  # se diagnostica.
  #
  # Sin RunAsDaemon, Tor hereda la salida del contenedor y sus mensajes
  # salen en `docker compose logs` mezclados con los nuestros, que es donde
  # se van a buscar. Al hacer exec, Tor queda adoptado por el proceso 1 y
  # sigue vivo igual que antes.
  tor --SocksPort 9050 --Log "notice stdout" &

  # 1. El SOCKS tiene que estar en pie antes de sondear nada.
  for i in $(seq 1 60); do
    if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(3); sys.exit(s.connect_ex(('127.0.0.1',9050)))" 2>/dev/null; then
      echo "[bip110] SOCKS de Tor escuchando."
      break
    fi
    sleep 2
  done

  # 2. Y ahora se sondea CADA nodo, no el primero que aparezca.
  #
  # Antes se cogia la primera .onion de las cuatro variables y se paraba
  # ahi. Como el canonico suele ser el primero, el arranque escribia "el
  # nodo responde por el servicio oculto" con el secundario inalcanzable.
  # Una comprobacion que pasa sin comprobar lo que importa es peor que no
  # tenerla: da por bueno justo el caso que hay que detectar.
  CORE_ONION=$(primera_onion "$BTC_RPC_TOR_URL" "$BTC_RPC_URL")
  KNOTS_ONION=$(primera_onion "$BTC_RPC_TOR_URL_KNOTS" "$BTC_RPC_URL_KNOTS")

  # El canonico bloquea el arranque: sin el no hay panel que servir.
  sondear "nodo canonico" "$CORE_ONION" \
          "$BTC_RPC_USER" "$BTC_RPC_PASSWORD" 60 || true

  # El secundario NO bloquea, solo informa. Que falte es una perdida de
  # capacidad (no se comparan las dos cadenas), no un motivo para no
  # arrancar, y el panel ya lo dice en pantalla y en /api/health.
  sondear "nodo secundario" "$KNOTS_ONION" \
          "${BTC_RPC_USER_KNOTS:-$BTC_RPC_USER}" \
          "${BTC_RPC_PASSWORD_KNOTS:-$BTC_RPC_PASSWORD}" 5 || true
fi

# UN solo worker, a proposito.
#
# La cache y la eleccion de direccion del nodo viven en memoria del
# proceso, asi que con dos workers cada uno tiene las suyas: el mismo
# escaneo caro se haria dos veces contra el nodo, y por Tor eso son
# minutos duplicados. El trabajo es de espera de red, no de CPU, asi que
# los hilos sobran para servir visitas.
exec gunicorn --bind 0.0.0.0:8110 --workers 1 --threads 16 --timeout 900 main:app
