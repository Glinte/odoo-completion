"""Public command line interface."""


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="0.1.0")
    parser.parse_args()
