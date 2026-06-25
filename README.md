# automation-jobs

Small automation scripts intended to run from GitHub Actions.

## Chiostro workshop email

Fetches the Chiostro workshop page, parses it with BeautifulSoup, renders the MJML email template, and sends it through Gmail.

```bash
python -m pip install -r requirements.txt
python scripts/chiostro_workshops_email.py --dry-run
```

## ETH value Slack message

Fetches the ETH/EUR quote from CoinMarketCap, multiplies it by the configured ETH amount, formats the value, and posts it to Slack.

```bash
python -m pip install -r requirements.txt
ETH_MULTIPLIER="your_eth_amount" python scripts/eth_value_slack.py --dry-run
```
