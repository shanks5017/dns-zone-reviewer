# 🚀 DNS Zone Reviewer - Demo Cheat Sheet

Use this file during your hackathon demo! Copy and paste these snippets at the bottom of `zones/example.com.txt` to trigger different AI responses.

---

## 🟢 Demo 1: Safe & Clean Change (Low Risk)
Show the judges that the bot approves safe, standard DNS modifications.

**What to copy:**
```text
; Safe TXT record for Google Site Verification
@   IN  TXT "google-site-verification=demo-safe-12345"
```
**Expected Result:** The PR comment will show a 🟢 **LOW** Risk Level and "Safe to Merge: ✅ Yes".

---

## 🔴 Demo 2: Dangerous Change (Critical Risk)
Show the judges how the bot catches critical misconfigurations that a human might miss.

**What to copy:**
```text
; DANGEROUS RECORD FOR DEMO - WILDCARD WITH LOW TTL
*.example.com. 60 IN A 203.0.113.5
```
**Expected Result:** The PR comment will show a 🔴 **CRITICAL** Risk Level, "Safe to Merge: ❌ No", and the AI will explain the dangers of Wildcard records and low TTL cache thrashing.
