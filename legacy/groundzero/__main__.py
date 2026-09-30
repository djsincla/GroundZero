"""
groundzero package __main__.py — enables `python -m groundzero`.

Run the GroundZero Assessment CLI:
    python -m groundzero --targets 10.0.0.1
    python -m groundzero --targets "10.0.0.0/24" --threads 8
"""
from groundzero.cli import main

if __name__ == "__main__":
    main()
