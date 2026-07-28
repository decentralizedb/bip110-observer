# BIP-110 Observer

A public dashboard for BIP-110 signalling that reads from **your own** Bitcoin
nodes. No block explorers, no third party APIs, no trusting anyone else's
count.

Bilingual (English and Spanish), a single HTML page, no framework, no build
step, and not one external resource.

---

## Why another one

Other BIP-110 dashboards already exist and they are good. They all answer the
same question though: *is it going to activate?* That is the question of
someone already in the debate.

This one also answers the questions everyone else is asking:

1. **Do I need to do anything?** Answered at the top of the page, before any
   chart. The answer is no.
2. **The three dates are three, not one.** Most coverage treats August 8th as
   a single event. Conflating them is the most common mistake in the debate.
3. **Can the minority chain survive?** A live simulator of block interval and
   time to the first difficulty retarget.
4. **What exactly is exempt**, taken from the BIP text itself.
5. **Who is actually signalling**, measured against an own node.

---

## Every number carries a label

This is the point of the project, and it drives every design decision.

| Level | Means | Used for |
|---|---|---|
| **Verifiable data** | Anyone with a full node gets the same figure | Miner signalling, chain comparison, BIP parameters |
| **Estimate** | A model or a sample, assumptions written next to it | Pool share, minority chain simulator |
| **Biased sample** | Does not represent the population, and says why | P2P node crawl |

Two rules follow, and they are not negotiable:

- **A number never gets promoted a level.** A sampled figure is never shown
  with the visual authority of a verified one.
- **Warnings are never hidden.** No tooltips, no accordions, no footnotes for
  the caveats. If a design change would look better by hiding a warning, the
  change is rejected.

The clearest case is the node count. It does **not** measure support for
BIP-110 and is never presented as if it did. A node does not publish its
consensus rules anywhere. The four reasons that sample is not a census are
printed on screen, in full.

---

## Quick start

```bash
git clone https://github.com/decentralizedb/bip110-observer.git
cd bip110-observer
cp .env.example .env && $EDITOR .env
docker compose up -d --build
curl -s localhost:8110/api/health
```

Everything the app needs, Tor included, is installed inside the container.
The host only needs Docker.

### Without Docker

```bash
cd app
python3 -m venv .venv && source .venv/bin/activate
pip install -r ../requirements.txt
CACHE_DIR=./data BTC_RPC_URL=http://NODE_IP:8332 \
BTC_RPC_USER=user BTC_RPC_PASSWORD=pass python main.py
```

---

## Configuration

### Two nodes, on purpose

| | `core` | `knots` |
|---|---|---|
| Variable | `BTC_RPC_URL` | `BTC_RPC_URL_KNOTS` |
| Software | Bitcoin Core | Bitcoin Knots with `reduced_data` |
| After block 961,632 | Stays on the majority chain | May follow the minority chain |

**Do not point the canonical node at a Knots node that enforces BIP-110.**
From block 961,632 it may end up on the minority chain, and the dashboard
would report that chain as if it were *the* chain. Check which is which:

```bash
bitcoin-cli getnetworkinfo    | grep REDUCED_DATA    # only the BIP-110 node
bitcoin-cli getdeploymentinfo | grep reduced_data    # only the BIP-110 node
```

The second node is optional. Without it the dashboard still works, but there
is no chain comparison and no way to detect a split.

### Clearnet and Tor, with failover

Each node accepts two addresses. **One is used**, the first that answers, and
if it stops answering the other is tried. They are never queried at once.

```
core   -> BTC_RPC_URL         then  BTC_RPC_TOR_URL
knots  -> BTC_RPC_URL_KNOTS   then  BTC_RPC_TOR_URL_KNOTS
```

Clearnet first because it is much faster. From a VPS it fails in a few
seconds and settles on Tor with no manual change. Every API response carries
`via: "clearnet" | "tor"`, because a dashboard whose whole point is knowing
where each number comes from cannot silently change transport.

`/api/health` warns about dangerous setups, including the silent one: both
nodes pointing at the same address would compare a node against itself, show
everything green, and never detect a split.

---

## Endpoints

| Route | Level | TTL | Notes |
|---|---|---|---|
| `/` | | | The dashboard |
| `/methodology`, `/metodologia` | | | Methodology, sources and limits |
| `/api/miners` | Data | 300s | Signalling in the current period |
| `/api/history` | Data | 3600s | Closed periods, with pool attribution |
| `/api/chain` | Data | 60s | State of the two chains |
| `/api/pools` | Estimate | 3600s | Pool share over a sample |
| `/api/nodes` | Biased sample | 3600s | P2P crawl |
| `/api/simulate?share=0.02` | Estimate | | One off calculation |
| `/api/params` | | | Parameters in use |
| `/api/health` | | | Both nodes, and warnings |

`/api/miners`, `/api/pools` and `/api/nodes` accept `?node=core|knots` and
default to `core`.

---

## Verification

Three tools, each protecting something different. All exit non zero on
failure, so they fit a CI job or a pre deploy hook.

```bash
cd app
python3 test_i18n.py    # i18n keys, placeholders, hardcoded figures, third party resources
python3 audit.py        # every figure recomputed against the node
node stress.js          # the real interface JS under 26 synthetic scenarios
```

`audit.py` reimplements signalling detection on purpose instead of importing
it: checking a function by calling that same function only confirms the same
bug twice. It also cross checks against `getdeploymentinfo`, the node's own
consensus counter, which is stronger evidence than agreeing with another
dashboard.

`stress.js` executes the page JavaScript with synthetic data and checks the
resulting HTML for unfilled placeholders, `NaN`, and above all for **text
that contradicts the data**: claiming the trend is flat while it rises, or
"only one pool signals" while six do.

Neither covers visual layout. That still needs a human looking at it.

---

## What this project does not do

Stated explicitly, because absences are easy to miss:

- It does not query mempool.space, blockstream.info or any external API.
- It loads no third party resources at all: no fonts, no CDN, no icons, no
  analytics. A test fails if any slip in.
- It does not measure support for BIP-110, because nothing observable does.
- It does not predict whether the proposal will activate.

---

## Parameters

Taken literally from the `Deployment` section of `bip-0110.mediawiki` in the
`bitcoin/bips` repository, version 1.0.0 (Status: Complete):

```
name:                  reduced_data
bit:                   4
starttime:             1764547200
timeout:               NO_TIMEOUT
max_activation_height: 965664
active_duration:       52416 blocks
threshold:             1109/2016 (55%)
```

| Block | What happens |
|---|---|
| 961,632 | Signalling becomes mandatory. **This is where the chains can separate** |
| 963,647 | End of the mandatory window, exactly one retarget period long |
| 963,648 | Forced lock in |
| 965,664 | The data rules take effect |

The split is not caused by the data rules. It is caused by the requirement to
signal. The rules arrive three weeks later.

Note that versionbits bit 4 was also used by BIP-91 in July 2017. The code
only scans the current retarget period so there is no collision today, but
any historical series would need the height range restricted.

Service bit 27 (`NODE_REDUCED_DATA`) is **not** part of BIP-110. It is
defined by Bitcoin Knots in `src/protocol.h`, inside the range Bitcoin's own
source reserves for temporary experiments, whose comment warns that service
bits are unauthenticated advertisements. The dashboard says so on screen.

---

## Contributing

Two rules are not stylistic preferences, they are what the project is:
no figure and no conclusion is ever hardcoded into a text, and no warning is
ever hidden. Pull requests that improve the look by removing a caveat will be
declined.

Before opening one, run the checks in `app/`: `test_i18n.py` for key parity,
placeholders and third party resources, `test_contrast.py` for both themes,
`stress.js` for the interface under data that has not happened yet, and
`audit.py` against a node. Any new check has to be seen failing on purpose
before it counts.

The code comments are in Spanish. The author is a Spanish language Bitcoin
educator and they are written for whoever maintains this. The user interface
itself is fully bilingual.

---

## License

MIT. See [LICENSE](LICENSE).

Built by Nobody / Decentralized ([@decentralized_b](https://x.com/decentralized_b)).
