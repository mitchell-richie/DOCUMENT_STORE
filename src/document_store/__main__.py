"""Entry point: python -m document_store"""

from document_store import __version__


def main() -> None:
    print(f"document_store {__version__}")
    
if __name__ == "__main__":
    main()