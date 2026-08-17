# 🦊 REX Fox

REX Fox is an advanced VAPT reconnaissance, admin/login panel finder, and passive vulnerability assessment tool designed for penetration testers and security researchers.

---

## ⚡ Key Features

* **Smart Crawling:** Automatically extracts endpoints from `robots.txt`, `sitemap.xml`, HTML source, and JS files.
* **Dynamic Wordlist Generation:** Automatically creates dynamic admin path combinations if no wordlist is provided.
* **Passive Vulnerability Checks:** Scans for sensitive files, directory listings, and misconfigured headers.
* **High-Speed Threading:** Supports concurrent multi-threading for fast discovery.

---
## 📥 Installation & Setup

**One-Line Installation & Shortcut Setup:**
```bash
cd ~ && rm -rf rexfox && git clone [https://github.com/rex7771/rexfox.git](https://github.com/rex7771/rexfox.git) && cd rexfox && chmod +x rexfox.py && sudo ln -sf "$(pwd)/rexfox.py" /usr/local/bin/rexfox

```
bash
git clone [https://github.com/rex7771/rexfox.git](https://github.com/rex7771/rexfox.git)
cd rexfox



bash
chmod +x rexfox.py

How to Update to the Latest Version:

Bash
cd ~/rexfox
git pull

🚀 Usage Examples
1. Basic Admin Panel Scan

Bashpython3 rexfox.py -u [https://example.com](https://example.com)

2. Deep Scan with Custom Wordlist & High Threads
Bashpython3 rexfox.py -u [https://example.com](https://example.com) -w wordlists/admin.txt -t 50
3. Large Auto-Generated Path Search (10,000 Paths)
Bashpython3 rexfox.py -u [https://example.com](https://example.com) --gen-count 10000 -o results/found.txt


⚙️ Command OptionsFlagLong ArgumentDescriptionDefault
-u--urlTarget website URLRequired
-w--wordlistCustom wordlist file pathAuto-generated
            --gen-countSize of auto-generated list5000
-t--threadsNumber of concurrent threads20
         --timeoutRequest timeout in seconds6
-o--outputSave results to fileDisabled
-c--crawlAuto-discover hidden pathsEnabled
           --no-crawlDisable path auto-discoveryDisabled
           --vuln-scanEnable passive headers/files checkEnabled
-q--quietShow report only after completionDisabled
⚠️ Disclaimer
This tool is created for authorized testing and educational purposes only. Unauthorized scanning of targets is strictly prohibited.
