"""Deprecated — use regenerate_one_scene.py."""
import sys

def main():
    print("Use: python scripts/regenerate_one_scene.py <output_folder> --scene N")
    print("Example: python scripts/regenerate_one_scene.py \"output/2026-05-06_26 v\" --scene 1")
    sys.exit(1)

if __name__ == "__main__":
    main()
