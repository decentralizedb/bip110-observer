#!/usr/bin/env bash
#
# Busca fugas antes de publicar nada. Recorre TODO el historial.
#
# LEE ESTO ANTES DE TOCARLO. Este script ha fallado dos veces:
#
#   1. Usaba `git grep -I`, y `-I` significa "ignora los binarios". Un
#      fichero de intercambio del editor, binario, que contenia una salida
#      de terminal con dos direcciones .onion dentro, paso el escaneo con
#      un "todo limpio". El escaneo que existe para evitar eso fue el que
#      lo dejo pasar.
#   2. Metia una tuberia dentro de la condicion (`if out=$(cmd | head)`),
#      con lo que el resultado no llegaba y encontraba cosas sin decirlo.
#
# De ahi que aqui se evite lo ingenioso: se recogen los hallazgos en un
# fichero y se cuenta cuantos hay. Es mas tonto y no miente.
#
# Uso:  ./deploy/scan-secrets.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
FALLOS=0
mal()  { printf '  FUGA    %s\n' "$1"; FALLOS=$((FALLOS+1)); }
bien() { printf '  ok      %s\n' "$1"; }

COMMITS=$(git rev-list --all 2>/dev/null || true)
NCOM=$(printf '%s\n' "$COMMITS" | grep -c . || true)

# Una direccion .onion v3 real son EXACTAMENTE 56 caracteres base32.
# Los ejemplos de la documentacion (tuservicioocultoxxxxxx...) tienen otra
# longitud y rachas largas del mismo caracter, cosa que una direccion real
# no tiene nunca. Sin esta distincion el escaneo marca su propia
# documentacion y acaba ignorandose.
es_onion_real() {
  local s="$1"
  [ "${#s}" -eq 56 ] || return 1
  printf '%s' "$s" | grep -qE '(.)\1{4,}' && return 1
  return 0
}

echo "== 1. direcciones .onion reales en cualquier commit =="
: > "$TMP/onion"
for c in $COMMITS; do
  # -a: tratar todo como texto. Sin esto los binarios se saltan.
  git grep -a -o -h -E '[a-z2-7]{50,60}\.onion' "$c" 2>/dev/null \
    | sed 's/\.onion$//' | sort -u | while read -r o; do
        es_onion_real "$o" && printf '%s %s\n' "${c:0:7}" "$o" >> "$TMP/onion"
      done
done
if [ -s "$TMP/onion" ]; then
  while read -r linea; do mal "onion real en el commit $linea"; done < <(sort -u "$TMP/onion")
else
  bien "ninguna direccion .onion real (los ejemplos de la documentacion no cuentan)"
fi

echo
echo "== 2. claves, tokens y credenciales =="
: > "$TMP/cred"
PATRONES=(
  '-----BEGIN (RSA|OPENSSH|EC|DSA|PGP|PRIVATE)'
  'AKIA[0-9A-Z]{16}'
  'gh[pousr]_[A-Za-z0-9]{16,}'
  'github_pat_[A-Za-z0-9_]{20,}'
  'xox[baprs]-[A-Za-z0-9-]{10,}'
  'sk-[A-Za-z0-9]{20,}'
  'AIza[0-9A-Za-z_-]{20,}'
  '(rpcpassword|rpcauth)[[:space:]]*='
  '(BTC_RPC_PASSWORD|BTC_RPC_USER)=[A-Za-z0-9]{6,}'
)
for pat in "${PATRONES[@]}"; do
  for c in $COMMITS; do
    git grep -a -n -E "$pat" "$c" 2>/dev/null | head -2 >> "$TMP/cred" || true
  done
done
# Los marcadores de la documentacion no son credenciales. Si no se
# excluyen, el escaneo marca sus propios ejemplos, y una comprobacion que
# grita sin motivo se acaba ignorando, que es peor que no tenerla.
MARCADORES='tu_usuario_rpc|tu_password_rpc|=usuario|=clave|=user|=pass|=tu_|YOUR_|xxxx|<[a-z_]+>|\$\{|:-\}'
grep -vE "$MARCADORES" "$TMP/cred" > "$TMP/cred2" 2>/dev/null || true
if [ -s "$TMP/cred2" ]; then
  while read -r l; do mal "${l:0:150}"; done < <(sort -u "$TMP/cred2" | head -10)
else
  bien "ninguna clave, token ni credencial"
fi

echo
echo "== 3. IPs privadas =="
: > "$TMP/ip"
for c in $COMMITS; do
  git grep -a -o -h -E '(192\.168|10\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}' "$c" 2>/dev/null \
    | sort -u >> "$TMP/ip"
done
# 192.168.1.50 y .51 son los ejemplos de la documentacion
REALES=$(sort -u "$TMP/ip" | grep -vE '^192\.168\.1\.(50|51)$|^10\.255\.255\.1$' || true)
if [ -n "$REALES" ]; then
  while read -r ip; do mal "IP privada real: $ip"; done <<< "$REALES"
else
  bien "solo las IPs de ejemplo de la documentacion"
fi

echo
echo "== 4. ficheros que nunca deberian estar =="
: > "$TMP/files"
for c in $COMMITS; do git ls-tree -r --name-only "$c" 2>/dev/null >> "$TMP/files"; done
RAROS=$(sort -u "$TMP/files" | grep -iE '(^|/)\.env$|swp$|swo$|~$|\.pem$|\.key$|\.p12$|torrc|hs_ed25519|rpcauth|\.tar\.gz$|(^|/)data/' || true)
if [ -n "$RAROS" ]; then
  while read -r f; do mal "fichero que no deberia estar: $f"; done <<< "$RAROS"
else
  bien "ningun fichero de credenciales, editor ni datos"
fi

echo
echo "== 5. inventario de lo que se publicaria =="
git ls-files | sed 's/^/            /'
echo "            ($(git ls-files | wc -l) ficheros, $NCOM commits)"

echo
if [ "$FALLOS" -eq 0 ]; then echo "LIMPIO"; else echo "$FALLOS problema(s): NO PUBLICAR"; fi
exit $((FALLOS > 0))
