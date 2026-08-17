#!/usr/bin/env python3
"""
Wordlist Generator for REX Fox
--------------------------------
Generates a large (~5000 entry) wordlist of common admin/login panel
paths by combining base keywords, CMS-specific paths, prefixes,
suffixes, and numeric variations. Output is a plain text file, one
path per line, ready to feed into rexfox.py with -w.

Usage:
    python3 wordlist_gen.py -o mywordlist.txt
    python3 wordlist_gen.py -o mywordlist.txt -n 8000
"""

import argparse
import random

# --- base keyword building blocks -------------------------------------
BASE_WORDS = [
    "admin", "administrator", "login", "signin", "panel", "cpanel",
    "control", "controlpanel", "manage", "manager", "management",
    "dashboard", "portal", "backend", "webadmin", "siteadmin",
    "sysadmin", "moderator", "staff", "root", "secure", "auth",
    "account", "accounts", "user", "users", "member", "members",
    "console", "adminpanel", "admincp", "admin-console",
    "admin_area", "adm", "webmaster", "operator", "supervisor",
    "office", "internal", "private", "restricted", "system",
    "config", "setup", "install", "master", "owner", "team",
]

CMS_SPECIFIC = [
    "wp-admin", "wp-admin/", "wp-login.php", "wp-login",
    "administrator/index.php", "administrator/", "phpmyadmin",
    "myadmin", "pma", "joomla/administrator", "typo3", "typo3/",
    "umbraco", "craft/admin", "concrete5/index.php/dashboard",
    "magento/admin", "shopadmin", "ghost/", "user/login",
    "wp-admin/admin.php", "wp-admin/index.php",
]

PREFIXES = ["", "old-", "new-", "backup-", "test-", "dev-", "staging-", "beta-", "my-", "secure-"]
SUFFIXES = ["", "1", "2", "01", "02", "2023", "2024", "2025", "_old", "_new", "_backup", "-panel", "-login", "-page"]
EXTENSIONS = ["", "/", ".php", ".html", ".asp", ".aspx", ".jsp"]

LOGIN_KEYWORDS = ["login", "signin", "log-in", "sign-in", "auth", "authenticate"]


def generate(target_count):
    words = set()

    # 1. base word x prefix x suffix x extension combos
    for base in BASE_WORDS:
        for prefix in PREFIXES:
            for suffix in SUFFIXES:
                for ext in EXTENSIONS:
                    words.add(f"{prefix}{base}{suffix}{ext}")
                    if len(words) >= target_count:
                        break

    # 2. base word + "/" + login keyword  (e.g. admin/login, panel/signin)
    for base in BASE_WORDS:
        for kw in LOGIN_KEYWORDS:
            for ext in ["", ".php", "/"]:
                words.add(f"{base}/{kw}{ext}")

    # 3. CMS-specific known paths (always included as-is)
    words.update(CMS_SPECIFIC)

    # 4. numbered variations of common bases (panel1..panel50 etc.)
    for base in ["admin", "panel", "portal", "login", "manage", "cp"]:
        for i in range(1, 60):
            words.add(f"{base}{i}")

    words = list(words)
    random.shuffle(words)  # randomize order for brute-force

    if len(words) > target_count:
        words = words[:target_count]

    return words


def main():
    parser = argparse.ArgumentParser(description="Generate a large admin/login path wordlist")
    parser.add_argument("-o", "--output", default="wordlist.txt", help="Output file path")
    parser.add_argument("-n", "--count", type=int, default=5000, help="Approximate number of entries to generate (default: 5000)")
    args = parser.parse_args()

    words = generate(args.count)

    with open(args.output, "w") as f:
        for w in words:
            f.write(w + "\n")

    print(f"[+] Generated {len(words)} paths -> {args.output}")


if __name__ == "__main__":
    main()
