import os

hero_dir = r"D:\[01] PROJECT\HERO"
keywords = ["raray", "vision", "hero/register", "hero/recognize", "api/v1/faces", "8000", "face_service"]
skip_dirs = {"node_modules", ".next", ".git", ".vercel", "dist", "build", ".gradle", "android", "ios", "backups"}

matches = []
for root, dirs, files in os.walk(hero_dir):
    dirs[:] = [d for d in dirs if d not in skip_dirs]
    for file in files:
        if file.endswith((".ts", ".tsx", ".js", ".jsx", ".json", ".env", ".example", ".local", ".dokploy", ".mjs")):
            fpath = os.path.join(root, file)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    found_kws = [kw for kw in keywords if kw.lower() in content.lower()]
                    if found_kws:
                        matches.append((fpath, found_kws))
            except Exception:
                pass

print(f"Total matching files in HERO: {len(matches)}")
for path, kws in matches:
    rel = os.path.relpath(path, hero_dir)
    print(f"- {rel} (found: {kws})")
