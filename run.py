"""Lanceur (utilisé aussi par PyInstaller)."""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--relais-raccourci":
        # Relais du raccourci lancé en administrateur : pas d'interface, pas de Qt.
        from assistant_pc.relais import main as relais
        sys.exit(relais(sys.argv[2:]))
    from assistant_pc.main import main
    sys.exit(main())
