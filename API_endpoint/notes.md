# xStocks API Notes

Base: `https://api.backed.fi/api/v2/public`. No authentication for the public endpoints below.

## Endpoint: Public Assets
- **Method**: GET
- **URL**: `https://api.backed.fi/api/v2/public/assets`
- **Query**: `?page=N` (1-based).
- **Purpose**: Returns the xStocks asset catalog.

### Pagination (confirmed 2026-09-12)
- Each page holds 100 assets in `nodes`.
- The `page` object holds `currentPage` and `hasNextPage`. There is no total count.
- Pages 1 to 7 hold 100 assets. Page 8 holds 32. Page 9 and later are empty.
- The catalog holds 732 assets. All symbols are unique. Pages do not overlap.

### Node Fields
- `id`, `name`, `symbol`, `isin`, `underlyingSymbol`, `underlyingIsin`
- `underlying` — object with `symbol`, `isin`, `type`, `listingCountry`
- `description`, `logo`, `isTradingHalted`
- `trading` — trading hours and order limits
- `deployments` — array of chains. Each has `address`, `network`, optional `wrapperAddressV2`, `supportsAtomicSwaps`, `stablecoins`

## Endpoint: Proof of Reserves
- **Method**: GET
- **URL**: `https://api.backed.fi/api/v2/public/proof-of-reserves`
- **Query**: `?page=N` (1-based).
- **Purpose**: Returns shares held and circulating supply per symbol.

### Pagination (confirmed 2026-09-12)
- Each page holds 100 items in `nodes`.
- The `page` object holds `currentPage`, `pageSize`, `totalPages`, `totalNodes`, `hasNextPage`, `hasPreviousPage`.
- The `totalNodes` value reports 830. The real total is 730. Use `hasNextPage`, not `totalNodes`.
- Pages 1 to 7 hold 100 items. Page 8 holds 30. The set holds 730 unique symbols and no duplicates.

### Node Fields
- `symbol` — the xStock symbol.
- `timestamp` — the snapshot time in ISO format.
- `sharesHeld` — a string. The shares in reserve. Example `"4082"`.
- `circulatingSupply` — a string. The supply that the public holds. Example `"3880.3515380051873531"`.
- `holdings` — array of `{ provider, quantity, symbol }`.

### Coverage
- All 730 reserve symbols exist in the asset catalog.
- Two assets have no reserve entry: `FGDLx` and `NWGx`.
- 9 assets have a `sharesHeld` of `"0"`. The script drops these.

### Supply Semantics (confirmed 2026-09-13)
- `circulatingSupply` is the token supply that the public holds. The minter holds the rest, so the value stays below the minted supply that a chain explorer shows. The two values never match.
- Sample: `FSLRx` reports a public supply of `0.957823495274543344`. The Solana mint `XsSbcq8MZso4DLAMgtRKjzCvgozdh4sje8PLj45kxJZ` holds 8 decimals and a minted supply of `24942.83932654`. The minter holds the other `24941.88` tokens. The tiny public supply shows that the asset is not in active public trading.
- The gap is not a unit or decimal fault. The minted supply divided by the public supply differs per asset: `SPYx` `1.25`, `NVDAx` `1.79`, `DRAMx` `23`, `FSLRx` `26041`, `AXTIx` `161068`.
- `sharesHeld` divided by `circulatingSupply` is about `1.00` for an actively traded asset: `SPYx` `1.02`, `NVDAx` `1.00`, `DRAMx` `1.00`. For a thin asset the same ratio is far above `1.00`: `FSLRx` `5.22`, `AXTIx` `12.18`, `MDBx` `20.2`.
- Market cap from this field is the value of the public supply, not a fully diluted value. Say so in the app.

## Endpoint: Asset Logo
- **Method**: GET
- **URL**: `https://xstocks-metadata.backed.fi/logos/tokens/{symbol}.png`
- **Purpose**: Returns the logo image for one asset.
- **Response**: `200` with `content-type: image/png`. Each image is 400 x 400 RGBA, about 15 KB.

### Confirmed 2026-09-12
- The assets API `logo` field holds this exact URL for every catalog entry. Zero entries differ.
- The URL is derived from the symbol. No asset call is needed.
- Edge cases work: `BRK.Bx`, `Ox`, `Ax`, and `Vx` all return `image/png`.
- A bad symbol returns `403` with `content-type: application/xml`, not `404`. Check the content type, not only the status code.

## Fetch Scripts

### scripts/fetch_logos.py
- `scripts/fetch_logos.py` downloads the logo for every symbol in `data/xstocks-assets.json`.
- Output: `data/logos/{symbol}.png`. The folder holds 723 files and about 18 MB.
- Existing files are skipped. Pass `--force` to overwrite them.
- A wrong content type is rejected, so an error page never lands in the folder.
- A failed write is removed. A partial file never stays behind.
- The script prints a counts block: downloaded, changed, unchanged, skipped, and failed.
- The exit code is non-zero when one or more downloads fail.
- Run from anywhere: `./scripts/fetch_logos.py`. Python 3 only. No third-party packages.

#### Logo Change Check
- Pass `--check-changes` to compare every saved logo with the server.
- The request carries the fingerprint of the saved file. When the image did not change, the server matches the fingerprint and answers `304` with no body. No image bytes cross the wire.
- A `200` answer with new bytes replaces the file and prints `CHANGED {symbol}`.
- A `200` answer with the saved bytes keeps the file. This guards against a foreign fingerprint scheme.
- A missing file takes the plain download path and prints `OK {symbol}`.
- A change prints the symbol list and a note to commit the replaced files. The logos are tracked in git.
- The check costs 723 small requests, about one minute. `--force` overrides the check and downloads every file.
- `--check-changes` on its own downloads a missing logo too. The flag does not skip a new symbol.

### scripts/market_calendar.py
- Owns every trading-day rule. Imported by `scripts/fetch_assets.py`. It is not run on its own.
- `MARKET_ZONE` is the exchange time zone: `America/New_York`.
- `is_trading_day(day)` returns True for a weekday that is not a market holiday.
- `market_is_open(moment)` returns True during the overnight leg (20:00 to 04:00 ET) and the day leg (04:00 to 20:00 ET).
- The overnight leg starts on Sunday night and ends on Friday morning. It does not run into a weekend or a holiday.
- `us_market_holidays(year)` returns the ten market holidays. A fixed holiday that falls on a weekend shifts to the observed day.

### scripts/fetch_assets.py
- Python 3 script for the assets, the reserves, and the quotes. No third-party packages.
- Output: `data/xstocks-assets.json`: array of `{ name, symbol, sharesHeld, circulatingSupply, price, priceUpdatedAt }`.
- The page reads that file with `fetch`, so no wrapper file is written.
- Two different groups. Do not mix them:
  - The drop rule removes an asset when the reserve row reports `sharesHeld` of `"0"`. The last run dropped 9.
  - An asset with no reserve row stays, with null values. The last run kept 2: `FGDLx` and `NWGx`.
- 723 assets remain. 721 have reserves. File size is about 100 KB.
- Values stay as strings, exactly as the API returns them.
- The script prints both groups. The first line holds the dropped count. The second line holds the dropped symbols.
- Adds a `price` field and a `priceUpdatedAt` field per asset.
- Quotes download only during a US session. The session rules live in `scripts/market_calendar.py`.
- The overnight leg runs from 20:00 to 04:00 ET, Sunday night through Friday morning.
- The day leg runs from 04:00 to 20:00 ET, Monday to Friday. It covers pre-market, regular, and after-hours trading.
- Market holidays are excluded. A holiday on a Monday also closes the Sunday-night leg. A holiday on a Friday also closes the Thursday-night leg.
- Outside the session the script skips every quote call and keeps the last known price.
- Quote calls run in a thread pool. The default is 8 workers. Set `--workers N` to change it.
- Quote calls share one pacer. Each call takes one time slot. The default gap is 0.25 seconds. Set `--min-interval S` to change it. The value 0 stops the pacing.
- The pacer holds every worker thread, so the flag caps the call rate for the whole run. 723 calls take at least 3 minutes at the default gap.
- A quote call makes 4 attempts. A 429 or 503 answer waits for the `Retry-After` header. Without that header the wait is 2, 4, then 8 seconds. The wait cap is 30 seconds.
- A 32-worker burst during a live session returned HTTP 429 Too Many Requests on many calls. The default is 8 workers now.
- The run prints the counts for fresh, retained, and unavailable prices. It also prints the `Rate limited quotes: N` line.
- `--force-quotes` fetches quotes outside a session.
- The script runs `scripts/fetch_logos.py` after the write. The logo script skips every saved file, so only a new logo downloads. The child also receives `--check-changes`, so every saved logo is compared with the server.
- `--no-logo-check` skips the compare and the extra requests. A new logo still downloads.
- A child failure prints a warning. The snapshot stays valid, so the parent keeps exit code 0.
- The API rejects the default urllib User-Agent with `403`. The script sends its own User-Agent.
- Run from anywhere: `./scripts/fetch_assets.py`.

## Endpoint: Asset Price Data
- **Method**: GET
- **URL**: `https://api.backed.fi/api/v2/public/assets/{symbol}/price-data`
- **Purpose**: Returns the current quote for one asset.
- **Response**: `{"quote": ...}`. The value is null outside a session.
- **Coverage**: One symbol per call. There is no bulk variant.
- **Missing symbol**: `ZZZZx` returns HTTP 404.

### Confirmed 2026-09-12
- Every tested symbol returned `{"quote":null}`. The market was closed (Saturday).
- Latency was about 21 seconds per symbol while the market was closed.
- Both hosts work: `api.backed.fi` and `api.xstocks.fi`.

### Confirmed 2026-09-13
- The OpenAPI spec states the response is `{ "quote": number | null }`.
- There is no bulk or multi-symbol quote endpoint. One call covers one symbol.
- The endpoint needs a User-Agent header. The default urllib agent gets `403`.
- A closed-market call answers in about 21 seconds with `{"quote": null}`.
- 32 concurrent calls all answered in about 21 seconds with zero errors.
- Overnight session: on Sunday 2026-09-13 at 21:03 ET, `AAPLx`, `TSLAx`, and `SPYx` each returned a real quote in about 0.5 to 0.7 seconds. The old gate treated the whole weekend as closed.

### Open Items
- The response holds one number. The `quote` field is `number | null`. No object fields exist.
- Latency in a session is about 0.5 to 0.7 seconds. The 21-second wait is a closed-market behavior.
- 723 calls at 8 workers take about 91 rounds. At about 0.7 seconds per call the step takes about 64 seconds.
- HTTP 429 rate limit: a 32-worker burst returned 429 on many calls on Sunday 2026-09-13 at 21:22 ET. 660 of 723 prices filled.
- The quote step paces its calls now. The default gap is one slot per 0.25 seconds. A 429 or 503 answer waits for `Retry-After`, then backs off. See the quote bullets under `scripts/fetch_assets.py`.
- Confirm the Sunday 20:00 ET open and the Friday 04:00 ET close on more dates. Only one observation exists.
- Confirm the holiday nights. Half days are untreated.

## Endpoint: Sibling Asset Paths
Documented on the same page. Not fetched yet.
- `GET /public/assets/{symbol}/multiplier`
- `GET /public/assets/{symbol}/multiplier/history`
- `GET /public/assets/{symbol}/circulating-supply`
- `GET /public/assets/{symbol}/total-supply`

### Supply Paths (confirmed 2026-09-13)
- `circulating-supply` returns one number in a `value` field.
- That number matches the reserve row for the symbol. Sample: `FSLRx` returns `0.9578234952745434`.
- `total-supply` returns a third number. Sample: `FSLRx` returns `266993.31182593195`.
- The three supply numbers differ. The script reads the reserve row only, so the JSON holds one source.

## Still Missing
- **Live price check**: a session run filled 660 of 723 quotes. Run the script with the 0.25-second pacer. Confirm that every price fills.
- **Session edges**: confirm the Sunday open and the Friday close on more dates.
- **Holiday nights**: half days are untreated.

## Docs
- API reference: `https://docs.xstocks.fi/apis/openapi`
- Version: v2. Base path: `/api/v2/*`.
