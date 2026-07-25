# Phase 11 — Strip Emoji from Outbound Tags

## Context

`vpn server change <name>` kills sing-box for 8/11 servers. Profile JSON outbound tags carry emoji suffixes (`🧠 ✂️`, `(Без рекламы) ✂️`) that `servers.yaml` doesn't include. `build_singbox_config()` sets `route.final` to a tag sing-box can't resolve → process dies.

Fix: normalize ALL tags (outbounds, route.final, route.rules) through `_normalize_tag()` in `sanitize_config()`, and normalize both sides in `_find_outbound()` and `build_singbox_config()`.

## Approach

### Step 1 — Add `_normalize_tag()` static helper in `provider.py`

Add `import re` at module top. Define regex covering emoji ranges:

```python
_EMOJI_RE = re.compile(
    "[\U0001F1E0-\U0001F1FF"   # flags
    "\U0001F300-\U0001F5FF"    # pictographs
    "\U0001F600-\U0001F64F"    # emoticons
    "\U0001F680-\U0001F6FF"    # transport
    "\U0001F900-\U0001F9FF"    # supplemental
    "\U00002600-\U000027BF"    # misc (⚡, ✂️, 🧠)
    "\U0000200D\U0000FE0F"     # ZWJ + VS16
    "\U000000A9\U000000AE"     # © ® (in case)
    "\u2800-\u28FF"            # Braille (in case)
    "]+"
)
```

Add static method:

```python
@staticmethod
def _normalize_tag(tag: str) -> str:
    """Strip emoji, '(Без рекламы)', and collapse whitespace from a tag."""
    tag = _EMOJI_RE.sub("", tag)
    tag = tag.replace("(Без рекламы)", "")
    return " ".join(tag.split()).strip()
```

### Step 2 — Fix `_find_outbound()` — normalize both sides

`provider.py` line 41-56. Change:

```python
def _find_outbound(self, tag_substring: str) -> dict[str, Any] | None:
    norm_sub = self._normalize_tag(tag_substring)
    profile = self._load_profile()
    for outbound in profile.get("outbounds", []):
        if norm_sub in self._normalize_tag(outbound.get("tag", "")):
            return outbound
    return None
```

### Step 3 — Fix `build_singbox_config()` — use normalized tag for route.final

`provider.py` line 109-136. After finding the target outbound by normalized match, use the REAL (un-normalized) tag for `route.final` — `sanitize_config()` will normalize it later:

```python
def build_singbox_config(self, server_name: str) -> str:
    config = self._load_profile()
    raw_tag: str = self._servers_config.servers[server_name].tag
    norm_sub = self._normalize_tag(raw_tag)

    # Find the real outbound tag by normalized substring match
    target: str | None = None
    for ob in config.get("outbounds", []):
        if norm_sub in self._normalize_tag(ob.get("tag", "")):
            target = ob["tag"]
            break
    if target is None:
        raise KeyError("Server %r not found in profile" % server_name)

    for rule in config.get("route", {}).get("rules", []):
        if rule.get("outbound") == "urltest_out":
            rule["outbound"] = target
    if config.get("route", {}).get("final") == "urltest_out":
        config["route"]["final"] = target

    sanitized = self.sanitize_config(config)
    return json.dumps(sanitized, indent=2)
```

### Step 4 — Fix `sanitize_config()` — normalize outbound tags + route.final + route.rules

`provider.py` line 138-210. Add at the END, before `return raw`:

```python
# Normalize all outbound tags (strip emoji suffixes from Akonit)
for outbound in raw.get("outbounds", []):
    tag = outbound.get("tag", "")
    normalized = self._normalize_tag(tag)
    if normalized != tag:
        outbound["tag"] = normalized
        logger.info("Sanitized: normalized tag %r -> %r", tag, normalized)

# Normalize route.final to match normalized outbound tags
if "route" in raw and raw["route"].get("final"):
    raw["route"]["final"] = self._normalize_tag(raw["route"]["final"])

# Normalize outbound references in route rules
for rule in raw.get("route", {}).get("rules", []):
    ob = rule.get("outbound", "")
    if ob and ob != "urltest_out":
        rule["outbound"] = self._normalize_tag(ob)
```

### Step 5 — Remove `default` stripping from urltest in `sanitize_config`

`provider.py` lines 177-181. DELETE the block that removes `default` from urltest/selector outbounds. sing-box v1.12.17 accepts it.

## Critical files

- `src/vpn/adapters/akonit/provider.py` — all changes: `_EMOJI_RE`, `_normalize_tag()`, `_find_outbound()`, `build_singbox_config()`, `sanitize_config()`

## Verification

1. `python3 -c "compile(open('...provider.py').read(), ...)"` — syntax OK
2. `docker build --no-cache` succeeds
3. Deploy → bootstrap works (route.final stays valid)
4. `vpn server change zonda` → IP changes, sing-box alive ✅
5. `vpn server change ponent` → IP changes, sing-box alive ✅
6. `vpn server change shamal` → IP changes, sing-box alive ✅
7. `vpn server list` shows all 11 servers (no "not found" errors)
8. All 11 servers switch without crash: `for s in zonda gregal sirokko siverko zefir verkhovik shamal ponent garbi biza barguzin; do vpn server change $s && sleep 2 && curl -s --socks5-hostname 127.0.0.1:3066 --max-time 5 https://ifconfig.me; done`
