# automation-jobs

Small automation scripts intended to run from GitHub Actions.

## Chiostro workshop email

This job re-implements the n8n workflow that:

1. Fetches `https://chiostrodelleillusioni.com/workshop-adulti-biella/`.
2. Parses the page with BeautifulSoup and extracts available workshops plus `workshop su richiesta`.
3. Renders a responsive MJML email template with linked workshop titles and a requested-workshops list.
4. Sends an HTML email through Gmail SMTP on Monday, Thursday, and Saturday.

### Required GitHub Actions secrets

Set these repository secrets before enabling the workflow:

| Secret | Description |
| --- | --- |
| `GMAIL_ADDRESS` | Gmail account used to send the email. |
| `GMAIL_APP_PASSWORD` | Google app password for that Gmail account. |
| `EMAIL_TO` | Recipient email address. |

Optional environment variables:

| Variable | Default |
| --- | --- |
| `WORKSHOP_URL` | `https://chiostrodelleillusioni.com/workshop-adulti-biella/` |
| `EMAIL_SUBJECT` | `Prossimi workshop al Chiostro delle Illusioni` |
| `EMAIL_FROM` | `GMAIL_ADDRESS` |
| `EMAIL_TEMPLATE_PATH` | `templates/chiostro_workshops.mjml` |
| `GMAIL_SMTP_HOST` | `smtp.gmail.com` |
| `GMAIL_SMTP_PORT` | `587` |

### Run locally

```bash
python -m pip install -r requirements.txt
python scripts/chiostro_workshops_email.py --dry-run
```

Remove `--dry-run` and set the Gmail variables to send the email.

For Gmail SMTP, use a Google app password rather than your normal Google
account password. Google requires 2-Step Verification before app passwords are
available.

The GitHub Actions workflow runs on Monday, Thursday, and Saturday at 07:30
Europe/Rome time during daylight saving time.
