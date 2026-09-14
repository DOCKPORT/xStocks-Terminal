`Repo in early stages of development.`

# xStocks Terminal

A web app that shows all xStocks tokenized equities in one place.

## What It Does
- Lists every available xStock with a logo, company name, and symbol.
- Shows shares held and circulating supply per symbol.
- Computes market cap per symbol from price and circulating supply.
- Shows a market cap chart, a total market cap value, and a GICS sector chart.

## Data
- Base info (symbols, name, logo) and proof of reserves (shares held, circulating supply) come from the public xStocks API. The price comes from the asset price data API.
- GICS sector and market cap are computed by this project.
- Assets with a shares held value of zero are dropped.

## Stack
- Python scripting.
- Github actions.
- HTML, CSS, and JavaScript.
- Deployed to Vercel.

