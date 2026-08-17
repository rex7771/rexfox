#!/usr/bin/env python3
"""
REX Fox — Admin / Login Panel Finder   (single-file, all-in-one)
-------------------------------------------------------------------
VAPT recon tool — everything in ONE file, no separate scripts needed:

  1. WORDLIST  — auto-generates a large (default 5000) admin/login
                 path wordlist internally, OR use your own with -w.
  2. CRAWL     — auto-discovers extra paths from robots.txt,
                 sitemap.xml, page source (view-source), and JS files,
                 so renamed panels (e.g. "/light") get caught even if
                 they're not in the wordlist, as long as the site
                 links to them somewhere.
  3. SCAN      — brute-forces every path, follows redirects, and
                 shows you exactly where a guessed path (e.g.
                 wp-admin) actually redirects to on the real site.
  4. CLASSIFY  — reads each found page's real HTML content and sorts
                 results into clearly separated groups: ADMIN LOGIN
                 PANEL, ADMIN PANEL (site), LOGIN SITE, and OTHER —
                 plus a breakdown by HTTP status code (200 / 301 / 302
                 / 401 / 403), each shown as its own section.

Usage (simplest — everything automatic):
    python3 rexfox.py -u https://target.com

Usage (your own wordlist):
    python3 rexfox.py -u https://target.com -w mywordlist.txt -t 30

Usage (save results + save the wordlist used, for reuse/editing):
    python3 rexfox.py -u https://target.com -o results.txt --save-wordlist mywordlist.txt

Other options:
    python3 rexfox.py -u https://target.com --no-crawl        # wordlist only, skip crawling
    python3 rexfox.py -u https://target.com --gen-count 10000 # bigger auto wordlist
    python3 rexfox.py --version

Wordlist file format (if you use -w): one path per line, e.g.
    admin
    light
    admin/login
    portal2024

⚠ Legal / ethical use only: run this ONLY against systems you own or
have explicit written authorization to test.
"""

import argparse
import sys
import time
import re
import random
import threading
import itertools
import concurrent.futures
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from colorama import init, Fore, Style
import pyfiglet

VERSION = "4.3.0.0"

init(autoreset=True)

# ---------------------------------------------------------------------
# Built-in default path list — building blocks for the internal
# wordlist generator (used automatically when no -w file is given,
# so you never need a separate wordlist file unless you want a
# custom one)
# ---------------------------------------------------------------------
DEFAULT_PATHS = [
    "admin", "admin/", "admin/login", "admin/login.php", "admin.php",
    "administrator", "administrator/", "administrator/index.php",
    "login", "login.php", "login/", "user/login", "users/login",
    "wp-admin", "wp-login.php", "cpanel", "panel", "controlpanel",
    "control", "manage", "manager", "management", "adminpanel",
    "admin_area", "admin-console", "admincp", "moderator",
    "moderator/login", "webadmin", "siteadmin", "adm", "backend",
    "admin/dashboard", "dashboard", "phpmyadmin", "myadmin",
    "sysadmin", "root", "secure", "portal", "portal/login",
    "account/login", "accounts/login", "signin", "sign-in", "auth",
    "auth/login", "api/admin",
]

CMS_SPECIFIC = [
    "wp-admin", "wp-admin/", "wp-login.php", "wp-login",
    "administrator/index.php", "administrator/", "phpmyadmin",
    "myadmin", "pma", "joomla/administrator", "typo3", "typo3/",
    "umbraco", "craft/admin", "concrete5/index.php/dashboard",
    "magento/admin", "shopadmin", "ghost/", "user/login",
    "wp-admin/admin.php", "wp-admin/index.php",
]

GEN_PREFIXES = ["", "old-", "new-", "backup-", "test-", "dev-", "staging-", "beta-", "my-", "secure-"]
GEN_SUFFIXES = ["", "1", "2", "01", "02", "2023", "2024", "2025", "_old", "_new", "_backup", "-panel", "-login", "-page"]
GEN_EXTENSIONS = ["", "/", ".php", ".html", ".asp", ".aspx", ".jsp"]
GEN_LOGIN_KEYWORDS = ["login", "signin", "log-in", "sign-in", "auth", "authenticate"]


def generate_wordlist(target_count=5000):
    """Built-in wordlist generator (merged from wordlist_gen.py) —
    combines base admin/login keywords with prefixes, suffixes, and
    extensions to produce a large candidate path list on the fly.
    No separate file needed unless you want to supply your own."""
    words = set()

    for base in DEFAULT_PATHS:
        base_clean = base.strip("/")
        if not base_clean:
            continue
        for prefix in GEN_PREFIXES:
            for suffix in GEN_SUFFIXES:
                for ext in GEN_EXTENSIONS:
                    words.add(f"{prefix}{base_clean}{suffix}{ext}")
                    if len(words) >= target_count:
                        break

    for base in DEFAULT_PATHS:
        base_clean = base.strip("/")
        for kw in GEN_LOGIN_KEYWORDS:
            for ext in ["", ".php", "/"]:
                words.add(f"{base_clean}/{kw}{ext}")

    words.update(CMS_SPECIFIC)

    for base in ["admin", "panel", "portal", "login", "manage", "cp"]:
        for i in range(1, 60):
            words.add(f"{base}{i}")

    # nested 2-segment combinations, e.g. "example/test", "internal/portal" —
    # catches panels one directory deeper than the site root, which a
    # single-word wordlist alone would miss
    generic_first_segments = [
        "internal", "private", "staff", "team", "office", "backend",
        "system", "secure", "restricted", "core", "base", "hub",
        "site", "app", "web", "main", "sys", "corp", "company",
    ]
    generic_second_segments = [
        "admin", "login", "panel", "portal", "dashboard", "manage",
        "control", "access", "auth", "signin", "console", "test",
        "staging", "dev", "backend", "cp",
    ]
    nested_budget = max(0, target_count - len(words))
    nested_added = 0
    for first in generic_first_segments:
        for second in generic_second_segments:
            if nested_added >= nested_budget:
                break
            words.add(f"{first}/{second}")
            nested_added += 1
        if nested_added >= nested_budget:
            break

    words = list(words)
    random.shuffle(words)
    if len(words) > target_count:
        words = words[:target_count]
    return words


# ---------------------------------------------------------------------
# Content-based classifiers — this is what lets the tool catch
# renamed panels like "/light/" that don't look like admin paths.
#
# IMPORTANT: a real login/admin panel means there's an actual LOGIN
# FORM on the page (a password field). Just seeing the word
# "dashboard" or "admin" mentioned in normal page text (marketing
# copy, a feature description, a nav label) is NOT enough — that
# caused false positives before (e.g. a public "/client-dashboard/"
# marketing page with no login form got wrongly tagged as an admin
# panel). So classification now requires a password field first,
# then uses context words only to decide WHAT KIND of login it is.
# ---------------------------------------------------------------------
PASSWORD_FIELD_REGEX = re.compile(r"""type=["']password["']""")

LOGIN_FORM_HINTS = [
    r"\bsign\s?in\b", r"\blog\s?in\b", r"\busername\b",
    r"forgot\s+password", r"remember\s+me", r"name=[\"']password[\"']",
]

ADMIN_CONTEXT_WORDS = [
    r"\badmin(istrator)?\b", r"\bcontrol\s?panel\b", r"\bcms\b",
    r"\bstaff\s?(login|portal|area)\b", r"\bemployee\s?(login|portal)\b",
    r"\bback\s?office\b", r"\bmanagement\s+console\b", r"\bwp-admin\b",
    r"\bsuper\s?admin\b", r"\bsystem\s+admin\b",
]

CLIENT_CONTEXT_WORDS = [
    r"\bclient\s?(login|portal|area|dashboard)\b",
    r"\bcustomer\s?(login|portal|area)\b",
    r"\bmember\s?(login|portal|area)\b",
    r"\byour\s+account\b", r"\buser\s?portal\b",
]

REX_FOX_ART = r"""
        ,     ,
       (\____/)
        (_oo_)      REX FOX
         (O)          hunts your admin panels
       __||__    \)
     []/______\[]
     / \______/ \
    /    /__\    \
   (\   /____\   /)
"""


def show_banner():
    logo = pyfiglet.figlet_format("REX FOX", font="big")
    print(Fore.RED + Style.BRIGHT + logo)
    print(Fore.RED + REX_FOX_ART)
    print(Fore.MAGENTA + Style.BRIGHT + f"        REX FOX — Shikdar   v{VERSION}")
    print(Fore.MAGENTA + Style.BRIGHT + "        Admin & Login Panel Discovery Tool — Nexus VAPT Recon")
    print(Fore.YELLOW + "        Use only on systems you are authorized to test.\n")
    print(Fore.GREEN + Style.BRIGHT + "  [+] Initializing scan engine..." + Style.RESET_ALL)
    time.sleep(0.3)
    print(Fore.GREEN + "  [+] Loading wordlist..." + Style.RESET_ALL)
    time.sleep(0.2)


def load_wordlist(path):
    """Stream a wordlist file of any size, one path per line."""
    words = []
    with open(path, "r", errors="ignore") as f:
        for line in f:
            w = line.strip()
            if w and not w.startswith("#"):
                words.append(w)
    return words


# ---------------------------------------------------------------------
# AUTO-DISCOVERY (crawling): finds paths NOT in your wordlist by
# reading what the target site itself references — robots.txt,
# sitemap.xml, page source (view-source), and linked JS files.
# This is how a renamed panel like "/light" gets caught even if
# you never typed "light" into a wordlist: if the site links to it
# anywhere, the crawler picks it up.
#
# What this can NOT do: guess a path that is never referenced
# ANYWHERE (not linked, not in JS, not in robots/sitemap) and isn't
# in your wordlist either. No tool can find that without a match —
# that's just how brute-force + crawling works.
# ---------------------------------------------------------------------
PATH_REGEX = re.compile(r"""["'](/[a-zA-Z0-9_\-./]{2,80}?)["']""")

INTERESTING_HINTS = [
    "admin", "login", "signin", "panel", "cpanel", "dashboard",
    "portal", "manage", "control", "auth", "backend", "console",
    "wp-admin", "wp-login", "api", "config", "setup", "account",
]


def fetch(url, timeout):
    try:
        return requests.get(url, timeout=timeout, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (RexFox VAPT Tool)"})
    except requests.RequestException:
        return None


def discover_from_robots(base_url, timeout):
    found = set()
    r = fetch(urljoin(base_url, "/robots.txt"), timeout)
    if r and r.status_code == 200:
        for line in r.text.splitlines():
            line = line.strip()
            if line.lower().startswith(("disallow:", "allow:", "sitemap:")):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    val = parts[1].strip()
                    if val.startswith("/"):
                        found.add(val)
    return found


def discover_from_sitemap(base_url, timeout):
    found = set()
    r = fetch(urljoin(base_url, "/sitemap.xml"), timeout)
    if r and r.status_code == 200:
        try:
            soup = BeautifulSoup(r.text, "xml")
            for loc in soup.find_all("loc"):
                path = urlparse(loc.text.strip()).path
                if path:
                    found.add(path)
        except Exception:
            pass
    return found


def discover_from_html(base_url, timeout, extra_pages=None):
    """Parses a page's view-source for <a>, <form>, <script>, <link> refs.
    If extra_pages is given, also crawls those internal pages (depth-2
    crawl) to surface links that only appear on inner pages, not just
    the homepage."""
    found = set()
    js_urls = set()
    pages_to_scan = [base_url] + (extra_pages or [])
    domain = urlparse(base_url).netloc

    for page_url in pages_to_scan:
        r = fetch(page_url, timeout)
        if not r or r.status_code >= 400:
            continue
        try:
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception:
            continue

        tags_attrs = [("a", "href"), ("form", "action"), ("link", "href"), ("script", "src")]
        for tag, attr in tags_attrs:
            for el in soup.find_all(tag):
                val = el.get(attr)
                if not val:
                    continue
                parsed = urlparse(urljoin(page_url, val))
                if parsed.netloc != domain:
                    continue  # skip external/off-site links
                path = parsed.path
                if not path or path == "/":
                    continue
                if tag == "script" and path.endswith(".js"):
                    js_urls.add(urljoin(page_url, val))
                found.add(path)

        for match in PATH_REGEX.findall(r.text):
            found.add(match)

    return found, js_urls


def discover_from_js(js_urls, timeout, max_files=15):
    """Regex-scans linked JS files for API/admin-style endpoint strings —
    a common place SPA/React/Vue apps hide real backend routes."""
    found = set()
    for js_url in list(js_urls)[:max_files]:
        r = fetch(js_url, timeout)
        if not r or r.status_code != 200:
            continue
        for match in PATH_REGEX.findall(r.text):
            found.add(match)
    return found


# ---------------------------------------------------------------------
# VULNERABILITY ASSESSMENT (passive / non-exploitative checks only)
#
# This checks for common MISCONFIGURATIONS — things that are visible
# just by requesting a URL and reading headers/content. It does NOT
# attempt any exploitation (no SQLi/XSS payloads, no login brute
# force, no attacks). That's the standard, safe scope for automated
# recon tooling; anything beyond this (actually exploiting a finding)
# is a separate, deliberate manual step in a real VAPT engagement.
# ---------------------------------------------------------------------
SECURITY_HEADERS_TO_CHECK = [
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Strict-Transport-Security",
    "Referrer-Policy",
]

SENSITIVE_FILES = [
    ".git/config", ".git/HEAD", ".env", ".env.bak", ".DS_Store",
    "wp-config.php.bak", "config.php.bak", "config.php.old",
    "backup.zip", "backup.sql", "database.sql", "db.sql",
    "phpinfo.php", "info.php", ".htaccess", ".htpasswd",
    "web.config", "composer.json", "package.json",
    "server-status", ".well-known/security.txt",
]

DIR_LISTING_MARKERS = ["Index of /", "<title>Index of", "Directory listing for"]


def check_security_headers(base_url, timeout):
    """Flags standard protective headers that are missing on the target."""
    findings = []
    r = fetch(base_url, timeout)
    if not r:
        return findings
    for header in SECURITY_HEADERS_TO_CHECK:
        if header not in r.headers:
            findings.append(("Missing Security Header", base_url, f"{header} not set"))

    server = r.headers.get("Server", "")
    powered_by = r.headers.get("X-Powered-By", "")
    if server and re.search(r"\d", server):
        findings.append(("Server Version Disclosure", base_url, f"Server: {server}"))
    if powered_by:
        findings.append(("Technology Disclosure", base_url, f"X-Powered-By: {powered_by}"))

    return findings


def check_sensitive_files(base_url, timeout, threads=10):
    """Checks whether common sensitive/backup files are publicly reachable."""
    findings = []

    def probe(fname):
        url = base_url.rstrip("/") + "/" + fname
        r = fetch(url, timeout)
        if r and r.status_code == 200 and len(r.content) > 0:
            return ("Exposed Sensitive File", url, f"status=200 size={len(r.content)}")
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        for result in executor.map(probe, SENSITIVE_FILES):
            if result:
                findings.append(result)
    return findings


def check_directory_listing(urls, timeout):
    """Checks already-found URLs for enabled directory listing."""
    findings = []
    for url in urls:
        r = fetch(url, timeout)
        if not r or r.status_code != 200:
            continue
        for marker in DIR_LISTING_MARKERS:
            if marker.lower() in r.text[:2000].lower():
                findings.append(("Directory Listing Enabled", url, "index listing exposed"))
                break
    return findings


def run_vuln_assessment(base_url, found_urls, timeout):
    print(Fore.CYAN + "\n  [~] Vulnerability assessment: headers, exposed files, directory listing...")
    findings = []
    findings += check_security_headers(base_url, timeout)
    findings += check_sensitive_files(base_url, timeout)
    # only check directory listing on paths that already responded 200
    findings += check_directory_listing(found_urls[:50], timeout)
    print(Fore.CYAN + f"  [~] {len(findings)} finding(s) from vulnerability assessment\n")
    return findings


def run_discovery(base_url, timeout):
    print(Fore.CYAN + "  [~] Auto-discovery: checking robots.txt, sitemap.xml, page source, JS files...")

    robots_paths = discover_from_robots(base_url, timeout)
    sitemap_paths = discover_from_sitemap(base_url, timeout)

    # first pass: homepage only, to find internal pages worth crawling deeper
    html_paths_p1, js_urls_p1 = discover_from_html(base_url, timeout)

    domain = urlparse(base_url).netloc
    inner_pages = []
    for p in list(html_paths_p1)[:15]:
        if p.endswith(".js") or p in ("/robots.txt", "/sitemap.xml"):
            continue
        inner_pages.append(urljoin(base_url, p))

    print(Fore.CYAN + f"      [~] depth-2 crawl: following {len(inner_pages)} internal link(s) found on homepage...")

    # second pass: re-crawl homepage + inner pages together (depth-2)
    html_paths, js_urls = discover_from_html(base_url, timeout, extra_pages=inner_pages)
    js_paths = discover_from_js(js_urls, timeout)

    all_found = robots_paths | sitemap_paths | html_paths | js_paths

    # rank: paths containing an admin/login-style keyword go first
    def score(p):
        low = p.lower()
        return any(h in low for h in INTERESTING_HINTS)

    interesting = sorted([p for p in all_found if score(p)])
    other = sorted([p for p in all_found if not score(p)])

    print(Fore.CYAN + f"      robots.txt: {len(robots_paths)}  sitemap.xml: {len(sitemap_paths)}  "
                       f"page source: {len(html_paths)}  JS files: {len(js_paths)} ({len(js_urls)} scanned)")
    if interesting:
        print(Fore.GREEN + f"  [~] {len(interesting)} interesting path(s) discovered (admin/login-like keywords found)")
    print(Fore.CYAN + f"  [~] {len(all_found)} total unique path(s) discovered via crawling\n")

    # interesting ones first so they get scanned/reported early
    return interesting + other


def classify_content(body):
    """Look at actual page content to decide what kind of page this is.

    Requires a real login FORM (a password field) before calling
    anything a panel/login page at all — just mentioning a word like
    "dashboard" or "admin" in normal page text is not enough and
    used to cause false positives (a public marketing page titled
    "Client Dashboard" is not an admin panel). Once a password field
    is confirmed, context words decide whether it's an admin-facing
    panel, a customer-facing client portal, or an unclassified
    generic login."""
    text = body.lower()

    has_password_field = bool(PASSWORD_FIELD_REGEX.search(text))
    has_login_hint = any(re.search(pat, text) for pat in LOGIN_FORM_HINTS)

    if not (has_password_field or has_login_hint):
        return None  # just a normal page, no login form present at all

    is_admin_context = any(re.search(pat, text) for pat in ADMIN_CONTEXT_WORDS)
    is_client_context = any(re.search(pat, text) for pat in CLIENT_CONTEXT_WORDS)

    if is_admin_context:
        return "ADMIN LOGIN PANEL"
    elif is_client_context:
        # explicitly its own category — a client/customer portal is
        # NOT an admin panel, even though it has a real login form
        return "CLIENT LOGIN PORTAL"
    else:
        return "LOGIN SITE"  # has a login form, but no clear admin/client signal


def check_path(base_url, path, timeout):
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (RexFox VAPT Tool)"})

        # capture the full redirect chain: this is what reveals the
        # target's real (renamed) admin/login URL when a guessed path
        # like wp-admin redirects somewhere custom, e.g. /staffportal2024
        redirect_chain = [h.url for h in r.history] if r.history else []
        final_url = r.url  # final destination after following all redirects

        classification = None
        if r.status_code < 400 or r.status_code in (401, 403):
            try:
                classification = classify_content(r.text[:20000])
            except Exception:
                classification = None

        return (url, r.status_code, len(r.content), classification, redirect_chain, final_url)
    except requests.RequestException:
        return (url, None, None, None, [], None)


# ---------------------------------------------------------------------
# WILDCARD / CATCH-ALL BASELINE DETECTION
#
# Some sites (WAF/security-plugin protected, or SPA-style catch-all
# routing) return HTTP 200 with THE SAME page content for literally
# ANY path — including ones that don't exist. Without checking for
# this, every single path in a scan looks like a "hit", and if that
# shared fallback page happens to contain a login form (a maintenance
# page, a WAF block page, a generic homepage with a nav "Login" link),
# EVERY path gets wrongly classified as an admin/login panel.
#
# Fix: before scanning, request a few definitely-nonexistent random
# paths. If they all come back with the same status + (near-)same
# size, that's the site's "wildcard" signature — record it, and
# during the real scan, any hit matching that exact signature gets
# flagged and EXCLUDED from panel classification, not reported as a
# real find.
# ---------------------------------------------------------------------
import uuid


def detect_wildcard_baseline(base_url, timeout, samples=3):
    signatures = []
    for _ in range(samples):
        junk_path = f"__rexfox_nonexistent_{uuid.uuid4().hex[:16]}__"
        r = fetch(base_url.rstrip("/") + "/" + junk_path, timeout)
        if r is not None:
            signatures.append((r.status_code, len(r.content)))
        else:
            signatures.append((None, None))

    # if all samples agree on the same (status, size), the site is
    # returning a fixed fallback response for anything — that's our
    # wildcard baseline to exclude later
    statuses = set(s[0] for s in signatures)
    sizes = set(s[1] for s in signatures)
    if len(statuses) == 1 and len(sizes) == 1 and None not in statuses:
        return signatures[0]  # (status_code, size) — the wildcard signature
    return None


def is_wildcard_match(status, size, baseline, tolerance=5):
    if not baseline:
        return False
    base_status, base_size = baseline
    if status != base_status:
        return False
    if base_size is None or size is None:
        return False
    return abs(size - base_size) <= tolerance


SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class ProgressState:
    def __init__(self, total):
        self.total = total
        self.checked = 0
        self.found = 0
        self.lock = threading.Lock()
        self.done = False


def spinner_worker(state, start_time):
    """Runs in a background thread, redraws a live status line so the
    user always sees the tool is alive during long scans."""
    frames = itertools.cycle(SPINNER_FRAMES)
    while not state.done:
        with state.lock:
            checked, total, found = state.checked, state.total, state.found
        pct = (checked / total * 100) if total else 0
        elapsed = time.time() - start_time
        line = (f"  {next(frames)} Scanning... {checked}/{total} ({pct:5.1f}%)  "
                f"found={found}  elapsed={elapsed:5.1f}s")
        print(Fore.BLUE + line, end="\r")
        time.sleep(0.1)
    print(" " * 90, end="\r")


def run_scan(base_url, wordlist, threads, timeout, quiet=False):
    found = []
    # randomize scan order so requests don't hit paths in a predictable
    # sequence (helps against simple rate/pattern based blocking too)
    wordlist = wordlist[:]
    random.shuffle(wordlist)

    total = len(wordlist)
    print(Fore.CYAN + f"[*] Target   : {base_url}")
    print(Fore.CYAN + f"[*] Wordlist : {total} entries (randomized order)")
    print(Fore.CYAN + f"[*] Threads  : {threads}\n")

    # --- baseline check: is this site returning a fixed page for ANY
    # path (wildcard/catch-all)? if so, we must filter that out below,
    # or every path in the wordlist will look like a false "hit" ---
    print(Fore.CYAN + "  [~] Checking for wildcard/catch-all responses (baseline test)...")
    wildcard_baseline = detect_wildcard_baseline(base_url, timeout)
    if wildcard_baseline:
        b_status, b_size = wildcard_baseline
        print(Fore.YELLOW + Style.BRIGHT +
              f"  [!] WARNING: this site returns the SAME response (status={b_status}, size={b_size}) "
              f"for paths that DON'T exist.")
        print(Fore.YELLOW + "      Results matching this exact signature will be marked as WILDCARD "
                             "and excluded from panel classification.\n")
    else:
        print(Fore.GREEN + "  [~] No wildcard response detected — site returns real 404s for unknown paths.\n")

    state = ProgressState(total)
    start_time = time.time()
    spin_thread = threading.Thread(target=spinner_worker, args=(state, start_time), daemon=True)
    spin_thread.start()

    wildcard_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(check_path, base_url, p, timeout): p for p in wordlist}
        for future in concurrent.futures.as_completed(futures):
            url, status, size, classification, redirect_chain, final_url = future.result()

            with state.lock:
                state.checked += 1

            if status is None:
                continue

            if status in (200, 201, 301, 302, 401, 403):
                # if this response matches the site's wildcard signature,
                # it's a fake hit — the path almost certainly does NOT
                # really exist, the site is just always answering 200.
                if is_wildcard_match(status, size, wildcard_baseline):
                    wildcard_count += 1
                    classification = None  # never let a wildcard hit be "ADMIN PANEL"
                    tag = "[WILDCARD — likely fake, path probably doesn't exist]"
                    color = Fore.BLUE
                elif classification:
                    tag = f"[{classification}]"
                    color = Fore.RED + Style.BRIGHT
                else:
                    tag = "[FOUND]"
                    color = Fore.YELLOW

                if not quiet:
                    # live mode: print each hit as it comes in
                    print(" " * 90, end="\r")
                    if redirect_chain and final_url and final_url != url:
                        print(color + f"  {tag} {url}")
                        print(color + f"        └─> redirected to: {final_url}  (status={status}, size={size})")
                    else:
                        print(color + f"  {tag} {url}  (status={status}, size={size})")
                # in quiet mode: say nothing here — everything shows once,
                # at the end, in the final report only

                with state.lock:
                    state.found += 1
                found.append((url, status, size, classification, redirect_chain, final_url))

    if wildcard_count:
        print(" " * 90, end="\r")
        print(Fore.BLUE + f"\n  [~] {wildcard_count} path(s) filtered out as wildcard/fake matches "
                           f"(not real, excluded from panel results)\n")

    state.done = True
    spin_thread.join()
    return found


def main():
    parser = argparse.ArgumentParser(description="REX Fox - Admin/Login Panel Finder (VAPT recon tool)")
    parser.add_argument("-u", "--url", required=True, help="Target base URL (e.g. https://example.com)")
    parser.add_argument("-w", "--wordlist", help="Path to custom wordlist file (one path per line, any size). If omitted, a wordlist is auto-generated internally.")
    parser.add_argument("--gen-count", type=int, default=5000, help="Size of the auto-generated wordlist when -w is not given (default: 5000)")
    parser.add_argument("-t", "--threads", type=int, default=20, help="Number of concurrent threads (default: 20)")
    parser.add_argument("--timeout", type=int, default=6, help="Request timeout in seconds (default: 6)")
    parser.add_argument("-o", "--output", help="Save results to a file")
    parser.add_argument("--save-wordlist", help="Also save the (auto-generated or loaded) wordlist to this file for reuse/editing")
    parser.add_argument("-c", "--crawl", action="store_true", default=True,
                         help="Auto-discover extra paths from robots.txt, sitemap.xml, page source and JS files (default: on)")
    parser.add_argument("--no-crawl", dest="crawl", action="store_false",
                         help="Disable auto-discovery, use only the wordlist")
    parser.add_argument("--version", action="version", version=f"REX Fox {VERSION}")
    parser.add_argument("--vuln-scan", action="store_true", default=True,
                         help="Run passive vulnerability assessment (headers, exposed files, dir listing) — default: on")
    parser.add_argument("--no-vuln-scan", dest="vuln_scan", action="store_false",
                         help="Skip vulnerability assessment")
    parser.add_argument("-q", "--quiet", action="store_true", default=False,
                         help="Don't print each hit live during scanning — show nothing until the final report")
    args = parser.parse_args()

    show_banner()

    if not args.url.startswith(("http://", "https://")):
        args.url = "https://" + args.url

    if args.wordlist:
        try:
            wordlist = load_wordlist(args.wordlist)
        except FileNotFoundError:
            print(Fore.RED + f"[!] Wordlist file not found: {args.wordlist}")
            sys.exit(1)
    else:
        print(Fore.GREEN + f"  [+] No -w given — auto-generating a {args.gen_count}-entry wordlist internally...")
        wordlist = generate_wordlist(args.gen_count)

    if args.save_wordlist:
        with open(args.save_wordlist, "w") as f:
            for w in wordlist:
                f.write(w + "\n")
        print(Fore.CYAN + f"  [+] Wordlist saved to {args.save_wordlist} ({len(wordlist)} entries) — edit and reuse with -w\n")

    if args.crawl:
        discovered = run_discovery(args.url, args.timeout)
        existing = set(p.strip("/").lower() for p in wordlist)
        added = 0
        for p in discovered:
            key = p.strip("/").lower()
            if key and key not in existing:
                wordlist.append(p)
                existing.add(key)
                added += 1
        if added:
            print(Fore.GREEN + f"  [+] {added} new path(s) merged into scan list from auto-discovery\n")

    print(Fore.GREEN + f"  [+] {len(wordlist)} paths loaded. Starting scan...\n" + Style.RESET_ALL)

    start = time.time()
    found = run_scan(args.url, wordlist, args.threads, args.timeout, quiet=args.quiet)
    elapsed = time.time() - start

    print("\n" + Fore.CYAN + Style.BRIGHT + "=" * 70)
    print(Fore.CYAN + Style.BRIGHT + "  SCAN SUMMARY")
    print(Fore.CYAN + Style.BRIGHT + "=" * 70)
    if found:
        admin_logins = [f for f in found if f[3] == "ADMIN LOGIN PANEL"]
        client_portals = [f for f in found if f[3] == "CLIENT LOGIN PORTAL"]
        logins = [f for f in found if f[3] == "LOGIN SITE"]
        others = [f for f in found if not f[3]]

        print(Fore.WHITE + f"  Admin Login Panels found : " + Fore.RED + Style.BRIGHT + f"{len(admin_logins)}")
        print(Fore.WHITE + f"  Client Login Portals found: " + Fore.CYAN + f"{len(client_portals)}")
        print(Fore.WHITE + f"  Login Sites found        : " + Fore.YELLOW + f"{len(logins)}")
        print(Fore.WHITE + f"  Other responding paths   : " + Fore.BLUE + f"{len(others)}")

        # ---- THE section that matters: payload -> admin/login result, ----
        # full URLs, never truncated, always shown first and separately
        # from generic 200 OK noise. Client portals are shown in their
        # OWN box below — they are explicitly NOT counted as admin panels.
        print(Fore.RED + Style.BRIGHT + "\n" + "=" * 70)
        print(Fore.RED + Style.BRIGHT + f"  ADMIN LOGIN PANEL RESULTS ({len(admin_logins)})")
        print(Fore.RED + Style.BRIGHT + "=" * 70)
        if admin_logins:
            for url, status, size, classification, redirect_chain, final_url in admin_logins:
                payload = url.rsplit(args.url.rstrip("/"), 1)[-1] or "/"
                print(Fore.WHITE + f"\n  Payload   : {payload}")
                print(Fore.WHITE + f"  Requested : {url}")
                if final_url and final_url != url:
                    print(Fore.YELLOW + f"  Redirects to : {final_url}")
                print(Fore.GREEN + Style.BRIGHT + f"  Status    : {status} OK" if status == 200
                      else Fore.YELLOW + f"  Status    : {status}")
                print(Fore.RED + Style.BRIGHT + f"  Type      : {classification}")
        else:
            print(Fore.YELLOW + "\n  No path classified as a genuine admin login panel this run.")
            print(Fore.YELLOW + "  (A page needs an actual login FORM with an admin/staff context")
            print(Fore.YELLOW + "   to be counted here — not just a page mentioning \"admin\" or")
            print(Fore.YELLOW + "   \"dashboard\" in its text.)")

        if client_portals:
            print(Fore.CYAN + Style.BRIGHT + "\n" + "=" * 70)
            print(Fore.CYAN + Style.BRIGHT + f"  CLIENT LOGIN PORTALS ({len(client_portals)}) — NOT admin panels")
            print(Fore.CYAN + Style.BRIGHT + "=" * 70)
            for url, status, size, classification, redirect_chain, final_url in client_portals:
                print(Fore.WHITE + f"\n  Requested : {url}")
                if final_url and final_url != url:
                    print(Fore.YELLOW + f"  Redirects to : {final_url}")
                print(Fore.WHITE + f"  Status    : {status}")
                print(Fore.CYAN + f"  Type      : {classification} (customer-facing, not admin)")

        if logins:
            print(Fore.YELLOW + Style.BRIGHT + "\n" + "=" * 70)
            print(Fore.YELLOW + Style.BRIGHT + f"  OTHER LOGIN FORMS ({len(logins)}) — login form found, role unclear")
            print(Fore.YELLOW + Style.BRIGHT + "=" * 70)
            for url, status, size, classification, redirect_chain, final_url in logins:
                print(Fore.WHITE + f"\n  Requested : {url}")
                if final_url and final_url != url:
                    print(Fore.YELLOW + f"  Redirects to : {final_url}")
                print(Fore.WHITE + f"  Status    : {status}")
        print(Fore.RED + Style.BRIGHT + "\n" + "=" * 70)

        if others:
            print(Fore.BLUE + f"\n  OTHER FOUND PATHS ({len(others)}) — normal pages, not admin/login:")
            for url, status, size, _, redirect_chain, final_url in others:
                line = f"    - {url}"
                if final_url and final_url != url:
                    line += f"  ->  {final_url}"
                line += f"  [{status}]"
                print(Fore.WHITE + line)

        # ---- status code breakdown — plain full-URL lines, no fixed-width
        # box (a box corrupts once a URL is longer than the box width) ----
        print(Fore.CYAN + Style.BRIGHT + "\n" + "=" * 70)
        print(Fore.CYAN + Style.BRIGHT + "  STATUS CODE REPORT (200 / 301 / 302 / 401 / 403 shown separately)")
        print(Fore.CYAN + Style.BRIGHT + "=" * 70)

        status_groups = {}
        for url, status, size, classification, redirect_chain, final_url in found:
            status_groups.setdefault(status, []).append((url, size, classification, final_url))

        status_labels = {
            200: "200 OK",
            201: "201 CREATED",
            301: "301 MOVED PERMANENTLY (redirect)",
            302: "302 FOUND (redirect)",
            401: "401 UNAUTHORIZED (auth required)",
            403: "403 FORBIDDEN",
        }

        for status_code in sorted(status_groups.keys()):
            entries = status_groups[status_code]
            label = status_labels.get(status_code, f"{status_code}")
            color = Fore.GREEN if status_code == 200 else (
                Fore.YELLOW if status_code in (301, 302) else Fore.MAGENTA)
            print(color + Style.BRIGHT + f"\n  --- {label} — {len(entries)} path(s) ---")
            for url, size, classification, final_url in entries:
                tag = f"  [{classification}]" if classification else ""
                line = f"    - {url}"
                if final_url and final_url != url:
                    line += f"  ->  {final_url}"
                print(color + line + tag)
    else:
        print(Fore.YELLOW + "  No admin/login panels found.")
    print(Fore.CYAN + Style.BRIGHT + "\n" + "=" * 60)
    print(Fore.MAGENTA + f"  Scan completed in {elapsed:.2f}s — {len(wordlist)} paths checked\n")

    # ---- vulnerability assessment (separate system, own section) ----
    if args.vuln_scan:
        found_urls_only = [f[0] for f in found] if found else []
        vuln_findings = run_vuln_assessment(args.url, found_urls_only, args.timeout)

        print(Fore.MAGENTA + Style.BRIGHT + "=" * 70)
        print(Fore.MAGENTA + Style.BRIGHT + "  VULNERABILITY ASSESSMENT REPORT")
        print(Fore.MAGENTA + Style.BRIGHT + "=" * 70)

        if vuln_findings:
            vuln_groups = {}
            for vtype, vurl, detail in vuln_findings:
                vuln_groups.setdefault(vtype, []).append((vurl, detail))

            for vtype in sorted(vuln_groups.keys()):
                entries = vuln_groups[vtype]
                print(Fore.RED + Style.BRIGHT + f"\n  --- {vtype} — {len(entries)} finding(s) ---")
                for vurl, detail in entries:
                    print(Fore.WHITE + f"    - {vurl}")
                    print(Fore.YELLOW + f"        -> {detail}")
        else:
            print(Fore.GREEN + "\n  No common misconfigurations found in this pass.")
        print(Fore.MAGENTA + Style.BRIGHT + "\n" + "=" * 70 + "\n")
    else:
        vuln_findings = []

    if args.output and found:
        status_groups = {}
        for url, status, size, classification, redirect_chain, final_url in found:
            status_groups.setdefault(status, []).append((url, size, classification, final_url))

        with open(args.output, "w") as f:
            f.write(f"REX Fox v{VERSION} — scan results for {args.url}\n")
            f.write("=" * 60 + "\n\n")
            for status_code in sorted(status_groups.keys()):
                f.write(f"--- STATUS {status_code} ---\n")
                for url, size, classification, final_url in status_groups[status_code]:
                    label = classification or "FOUND"
                    if final_url and final_url != url:
                        f.write(f"[{label}] {url} -> {final_url} [{status_code}] size={size}\n")
                    else:
                        f.write(f"[{label}] {url} [{status_code}] size={size}\n")
                f.write("\n")

            if vuln_findings:
                f.write("=" * 60 + "\n")
                f.write("VULNERABILITY ASSESSMENT\n")
                f.write("=" * 60 + "\n\n")
                for vtype, vurl, detail in vuln_findings:
                    f.write(f"[{vtype}] {vurl} -> {detail}\n")

        print(Fore.CYAN + f"[*] Results saved to {args.output} (grouped by status code + vuln findings)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(Fore.RED + "\n[!] Scan interrupted by user.")
        sys.exit(1)
