#!/usr/bin/env bash
#
# Checks a deployed instance from the outside.
#
# Run it against the public URL after every deploy, and after touching
# anything in the CDN. The other three tools check the code; this one
# checks what the world actually receives, which is not the same thing.
#
# It asks with a browser User-Agent on purpose. A CDN may inject scripts
# only for requests that look like a browser, so checking with a plain
# curl call reports a clean page that nobody is actually being served.
# That exact blind spot let a Cloudflare analytics beacon through once.
#
# Usage: ./verify-live.sh https://your.domain
set -u

URL="${1:-}"
[ -z "$URL" ] && { echo "usage: $0 https://your.domain"; exit 2; }
URL="${URL%/}"

UA="Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
FAILS=0
ok()   { printf '  ok      %s\n' "$1"; }
fail() { printf '  FAIL    %s\n' "$1"; FAILS=$((FAILS+1)); }

echo "Checking $URL"
echo

# --- 1. the page is served at all -----------------------------------------
code=$(curl -s -o /dev/null -w '%{http_code}' -m 30 -A "$UA" "$URL/")
[ "$code" = "200" ] && ok "page returns 200" || fail "page returns $code"

html=$(curl -s -m 30 -A "$UA" -H 'Accept: text/html,application/xhtml+xml' "$URL/")
[ -n "$html" ] || { fail "empty response"; exit 1; }

# --- 2. nothing LOADED from anyone else ------------------------------------
#
# A link is not a resource. <a href="..."> goes somewhere if the visitor
# clicks it; <script src>, <img src> and <link href> download something
# without asking. Only the second kind breaks the promise this site makes
# about loading nothing from third parties.
#
# Lumping both together flagged the link to the project's own source code
# as a violation, which is the opposite of the point: that link exists so
# people can check the claims.
host=$(printf '%s' "$URL" | sed -E 's#^https?://##; s#/.*##')
externals=$( { printf '%s' "$html" | grep -oE '\bsrc="https?://[^"]+"' | sed -E 's/^src="//; s/"$//'
               printf '%s' "$html" | grep -oE '<link\b[^>]*href="https?://[^"]+"' | sed -E 's/.*href="//; s/".*//'
               printf '%s' "$html" | grep -oE '@import[^;]*https?://[^"'"'"');]+' | grep -oE 'https?://[^"'"'"');]+'
             } 2>/dev/null | grep -v "^https\?://$host" | sort -u)
if [ -z "$externals" ]; then
  ok "no third party resources"
else
  fail "third party resources served to browsers:"
  printf '            %s\n' $externals
fi

# --- 3. no injected analytics or script rewriting -------------------------
for pat in cloudflareinsights beacon.min.js rocket-loader data-cf-settings \
           email-decode googletagmanager google-analytics; do
  if printf '%s' "$html" | grep -qi "$pat"; then
    fail "injected: $pat"
  fi
done
printf '%s' "$html" | grep -qiE 'cloudflareinsights|rocket-loader|googletagmanager' \
  || ok "no injected analytics or script rewriting"

# --- 4. the API is never cached -------------------------------------------
hdr=$(curl -sI -m 30 -A "$UA" "$URL/api/params")
printf '%s' "$hdr" | grep -qi 'cache-control:.*no-store' \
  && ok "api sends no-store" || fail "api is missing Cache-Control: no-store"
if printf '%s' "$hdr" | grep -qiE 'cf-cache-status: *(HIT|EXPIRED|REVALIDATED)'; then
  fail "api is being cached by the CDN: $(printf '%s' "$hdr" | grep -i cf-cache-status)"
else
  ok "api not served from CDN cache"
fi

# --- 5. the data being served is recent -----------------------------------
#
# Not by comparing two calls seconds apart: the application caches on
# purpose (CHAINS_TTL), so two close calls returning the same payload is
# correct behaviour, not a CDN caching it. Comparing them reported a
# problem that did not exist. What matters is whether the figure being
# served is recent, and whether the CDN is the one answering.
now=$(date +%s)
body=$(curl -s -m 60 -A "$UA" "$URL/api/chain")
upd=$(printf '%s' "$body" | grep -o '"updated":[0-9]*' | head -1 | tr -d '"updated:')
if [ -z "$upd" ]; then
  fail "/api/chain did not answer with a timestamp"
else
  age=$((now - upd))
  if [ "$age" -lt 0 ]; then age=$((-age)); fi
  if [ "$age" -lt 600 ]; then
    ok "data is ${age}s old, well within its refresh window"
  else
    fail "data is ${age}s old: nothing has refreshed it in a long while"
  fi
fi
chdr=$(curl -sI -m 30 -A "$UA" "$URL/api/chain")
if printf '%s' "$chdr" | grep -qiE 'cf-cache-status: *(HIT|EXPIRED|REVALIDATED)' \
   || printf '%s' "$chdr" | grep -qiE '^age: *[1-9]'; then
  fail "a CDN is answering /api/chain from its own cache"
else
  ok "the CDN is not answering /api/chain from cache"
fi

# --- 6. the canonical URL matches where it is served ----------------------
canon=$(printf '%s' "$html" | grep -o '<link rel="canonical" href="[^"]*"' | sed -E 's/.*href="([^"]*)".*/\1/')
case "$canon" in
  *"$host"*) ok "canonical points at this host" ;;
  "")        fail "no canonical link" ;;
  *)         fail "canonical points elsewhere: $canon" ;;
esac

echo
if [ "$FAILS" -eq 0 ]; then
  echo "all good"
else
  echo "$FAILS problem(s)"
fi
exit $((FAILS > 0))
