import os

hero_dir = r"D:\[01] PROJECT\HERO"
target_dirs = ["app", "components", "lib"]
matches = []

for tdir in target_dirs:
    full_tdir = os.path.join(hero_dir, tdir)
    for root, dirs, files in os.walk(full_tdir):
        for file in files:
            if file.endswith((".tsx", ".ts", ".jsx", ".js")):
                fpath = os.path.join(root, file)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                        if "FACE RECOG BY AFI" in text or "Percobaan 1/" in text or "Percobaan " in text or "Mencocokkan Biometrik" in text or "Fast Auto-Biometrics" in text:
                            matches.append(fpath)
                except Exception:
                    pass

print("Found files:", matches)
