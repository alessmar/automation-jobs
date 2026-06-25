#!/usr/bin/env python3
"""Fetch Chiostro workshops, parse them deterministically, and email via SMTP."""

from __future__ import annotations

import os
import re
import smtplib
import sys
from dataclasses import dataclass
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from jinja2 import Environment, FileSystemLoader, select_autoescape
from mjml import mjml_to_html


DEFAULT_SUBJECT = "Prossimi workshop al Chiostro delle Illusioni"
DEFAULT_TEMPLATE_PATH = "templates/chiostro_workshops.mjml"
REQUEST_TIMEOUT_SECONDS = 45

MONTH_HEADING_RE = re.compile(r"Workshop mese di", re.IGNORECASE)
REQUESTED_HEADING_RE = re.compile(r"Workshop su Richiesta", re.IGNORECASE)
DATE_LINE_RE = re.compile(
    r"^\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
    r"settembre|ottobre|novembre|dicembre)(?:\s+\d{4})?$",
    re.IGNORECASE,
)
SEATS_LINE_RE = re.compile(r"^\d+\s*posti?$", re.IGNORECASE)
SOLD_OUT_RE = re.compile(r"sold\s*out|esaurit", re.IGNORECASE)


@dataclass(frozen=True)
class Workshop:
    title: str
    date: str
    seats: str
    url: str


@dataclass(frozen=True)
class RequestedWorkshop:
    title: str
    url: str


@dataclass(frozen=True)
class Settings:
    workshop_url: str
    smtp_password: str | None
    smtp_host: str
    smtp_port: int
    from_email: str | None
    to_email: str | None
    subject: str
    template_path: Path


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def log(message: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", file=sys.stderr, flush=True)


def load_settings() -> Settings:
    return Settings(
        workshop_url="https://chiostrodelleillusioni.com/workshop-adulti-biella/",
        smtp_password=env("SMTP_PASSWORD"),
        smtp_host=env("SMTP_HOST"),
        smtp_port=587,
        from_email=env("EMAIL_FROM"),
        to_email=env("EMAIL_TO"),
        subject=env("EMAIL_SUBJECT", DEFAULT_SUBJECT) or DEFAULT_SUBJECT,
        template_path=Path(env("EMAIL_TEMPLATE_PATH", DEFAULT_TEMPLATE_PATH) or DEFAULT_TEMPLATE_PATH),
    )


def fetch_workshop_page(url: str) -> str:
    log(f"Fetching workshop page: {url}")
    response = requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; automation-jobs/1.0; "
                "+https://github.com/actions)"
            )
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    log(f"Fetched workshop page: status={response.status_code}, bytes={len(response.content)}")
    return response.text


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def figure_title_lines(figcaption: Tag | None) -> list[str]:
    if figcaption is None:
        return []
    text = figcaption.get_text("\n", strip=True)
    return [normalize_space(line) for line in text.splitlines() if normalize_space(line)]


def parse_figure(figure: Tag, base_url: str) -> tuple[Workshop | RequestedWorkshop | None, str | None]:
    link = figure.find("a", href=True)
    url = urljoin(base_url, link["href"]) if link else base_url
    lines = figure_title_lines(figure.find("figcaption"))
    if not lines:
        return None, None

    date_value = "N/D"
    seats_value = "N/D"
    title_parts: list[str] = []

    for line in lines:
        if DATE_LINE_RE.match(line) and date_value == "N/D":
            date_value = normalize_space(line)
            continue
        if SEATS_LINE_RE.match(line) and seats_value == "N/D":
            seats_value = normalize_space(line)
            continue
        if SOLD_OUT_RE.search(line) and seats_value == "N/D":
            seats_value = "Sold out"
            continue
        title_parts.append(line)

    title = normalize_space(" ".join(title_parts)).strip(" -–—")
    if not title:
        return None, None

    return Workshop(title=title, date=date_value, seats=seats_value, url=url), seats_value


def append_unique(items: list, seen: set[str], key: str, value) -> None:
    if key not in seen:
        seen.add(key)
        items.append(value)


def extract_workshop_data(raw_html: str, base_url: str) -> tuple[list[Workshop], list[RequestedWorkshop]]:
    log("Parsing workshop page HTML with BeautifulSoup.")
    soup = BeautifulSoup(raw_html, "html.parser")
    main = soup.find("main") or soup.body or soup

    workshops: list[Workshop] = []
    requested_workshops: list[RequestedWorkshop] = []
    seen_workshops: set[str] = set()
    seen_requested: set[str] = set()

    section: str | None = None
    for node in main.descendants:
        if not isinstance(node, Tag):
            continue

        if node.name in {"h2", "h3", "h4", "h5"}:
            heading_text = normalize_space(node.get_text(" ", strip=True))
            if MONTH_HEADING_RE.search(heading_text):
                section = "available"
            elif REQUESTED_HEADING_RE.search(heading_text):
                section = "requested"
            continue

        if node.name != "figure" or section not in {"available", "requested"}:
            continue

        parsed, seats_value = parse_figure(node, base_url)
        if parsed is None:
            continue

        if section == "available":
            key = f"{parsed.title.lower()}|{parsed.date.lower()}|{parsed.url.lower()}"
            append_unique(workshops, seen_workshops, key, parsed)
        else:
            requested = RequestedWorkshop(title=parsed.title, url=parsed.url)
            key = f"{requested.title.lower()}|{requested.url.lower()}"
            append_unique(requested_workshops, seen_requested, key, requested)

    if not workshops:
        raise RuntimeError("No available workshops were found in the page.")

    log(f"Parsed workshops: available={len(workshops)}, requested={len(requested_workshops)}")
    return workshops, requested_workshops


def escape_md(text: str) -> str:
    return text.replace("|", "\\|")


def log_preview(workshops: list[Workshop], requested_workshops: list[RequestedWorkshop]) -> None:
    lines = [
        "Workshop preview (Markdown):",
        "| Workshop | Data | Posti |",
        "| --- | --- | --- |",
    ]
    for workshop in workshops:
        lines.append(
            f"| [{escape_md(workshop.title)}]({workshop.url}) | {escape_md(workshop.date)} | {escape_md(workshop.seats)} |"
        )
    print("\n".join(lines), file=sys.stderr)

    if requested_workshops:
        requested = ", ".join(f"[{escape_md(item.title)}]({item.url})" for item in requested_workshops)
        print(f"\nWorkshop su richiesta: {requested}\n", file=sys.stderr)


def render_email_html(settings: Settings, workshops: list[Workshop], requested_workshops: list[RequestedWorkshop]) -> str:
    log(f"Rendering MJML template: {settings.template_path}")
    template_path = settings.template_path
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent or Path("."))),
        autoescape=select_autoescape(default=True),
    )
    template = env.get_template(template_path.name)
    mjml_markup = template.render(
        workshops=workshops,
        requested_workshops=requested_workshops,
        subject=settings.subject,
        generated_at=datetime.now().strftime("%d/%m/%Y %H:%M"),
    )

    log(f"Compiling MJML to HTML with mjml-python: chars={len(mjml_markup)}")
    result = mjml_to_html(mjml_markup, template_dir=str(template_path.parent or Path(".")))
    if result.errors:
        raise RuntimeError(f"MJML render failed: {result.errors}")
    log(f"Compiled email HTML: chars={len(result.html)}")
    return result.html


def send_email(settings: Settings, html: str) -> None:
    missing = [
        name
        for name, value in {
            "SMTP_PASSWORD": settings.smtp_password,
            "EMAIL_FROM": settings.from_email,
            "EMAIL_TO": settings.to_email,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    log("Preparing SMTP message.")
    message = EmailMessage()
    message["From"] = settings.from_email
    message["To"] = settings.to_email
    message["Subject"] = settings.subject
    message.set_content("Il riepilogo dei workshop e disponibile nella versione HTML di questa email.")
    message.add_alternative(html, subtype="html")

    log(f"Connecting to SMTP: host={settings.smtp_host}, port={settings.smtp_port}")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=REQUEST_TIMEOUT_SECONDS) as smtp:
        log("Starting SMTP TLS.")
        smtp.starttls()
        log(f"Authenticating to SMTP server.")
        smtp.login(settings.from_email, settings.smtp_password)
        log(f"Sending email to {settings.to_email}.")
        smtp.send_message(message)

    log(f"Email sent via SMTP from {settings.from_email} to {settings.to_email}.")


def run(dry_run: bool) -> int:
    log(f"Starting Chiostro workshop email job: dry_run={dry_run}")

    settings = load_settings()
    log(f"Loaded settings: template={settings.template_path}")
    raw_html = fetch_workshop_page(settings.workshop_url)
    workshops, requested_workshops = extract_workshop_data(raw_html, settings.workshop_url)
    log_preview(workshops, requested_workshops)
    email_html = render_email_html(settings, workshops, requested_workshops)

    if dry_run:
        log("Dry run enabled; printing generated HTML and skipping email send.")
        print(email_html)
        return 0

    send_email(settings, email_html)
    log("Job completed successfully.")
    return 0


def parse_args() -> argparse.Namespace:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate the HTML and print it instead of sending the email.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return run(dry_run=args.dry_run)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
