import os

hero_dir = r"D:\[01] PROJECT\HERO"
target_dirs = ["app", "lib", "components", "hooks", "db", "scripts"]
keywords = ["raray", "vision", "hero/register", "hero/recognize", "api/v1/faces", "8000", "face"]

matches = []
for tdir in target_dirs:
    full_tdir = os.path.join(hero_dir, tdir)
    if not os.path.exists(full_tdir):
        continue
    for root, dirs, files in os.walk(full_tdir):
        for file in files:
            if file.endswith((".ts", ".tsx", ".js", ".jsx", ".json", ".mjs")):
                fpath = os.path.join(root, file)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        found = [kw for kw in keywords if kw.lower() in content.lower()]
                        if found:
                            matches.append((fpath, found))
                except Exception:
                    pass

# Also check root .env files
for env_file in [".env", ".env.local", ".env.example", ".env.dokploy", ".env.raray-vision.example"]:
    fpath = os.path.join(hero_dir, env_file)
    if os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                found = [kw for kw in keywords if kw.lower() in content.lower()]
                if found:
                    matches.append((fpath, found))
        except Exception:
            pass

print(f"Total matching files: {len(matches)}")
for path, found in matches:
    rel = os.path.relpath(path, hero_dir)
    print(f"• {rel} -> {found}")
