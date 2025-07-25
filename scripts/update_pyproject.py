# scripts/update_pyproject.py
import subprocess
import toml
from pathlib import Path

PYPROJECT_FILE = Path("pyproject.toml")

def get_outdated_packages():
    result = subprocess.run(
        ["poetry", "show", "--outdated", "--no-ansi"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        print("❌ Failed to run `poetry show --outdated`.")
        print(result.stderr)
        return []

    outdated = []
    for line in result.stdout.splitlines():
        # Format: name current latest description
        parts = line.split()
        if len(parts) >= 3:
            name, current, latest = parts[:3]
            outdated.append((name, current, latest))
    return outdated

def update_versions_in_pyproject(outdated_packages):
    pyproject = toml.load(PYPROJECT_FILE)

    updated = False
    for name, current, latest in outdated_packages:
        for section in ["dependencies", "dev-dependencies"]:
            deps = pyproject.get("tool", {}).get("poetry", {}).get(section, {})
            if name in deps:
                print(f"🔄 Updating {name} from {deps[name]} → ^{latest}")
                deps[name] = f"^{latest}"
                updated = True

    if updated:
        with open(PYPROJECT_FILE, "w") as f:
            toml.dump(pyproject, f)
        print("✅ pyproject.toml updated with latest compatible versions.")
    else:
        print("✅ No versions changed in pyproject.toml.")

def poetry_update():
    print("📦 Running `poetry update`...")
    subprocess.run(["poetry", "update"])

def main():
    print("🔍 Checking for outdated packages...")
    outdated = get_outdated_packages()
    if not outdated:
        print("🎉 All dependencies are up to date!")
        return

    update_versions_in_pyproject(outdated)
    poetry_update()

if __name__ == "__main__":
    main()
