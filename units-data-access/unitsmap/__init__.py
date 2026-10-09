"""unitsmap: map what is inside a PowerBuilder application such as Auto-IT Units.

It reads the application's own files (.pbd/.pbl libraries, .psr saved reports, .ini
connection settings) and shows which database tables and columns sit behind every screen,
the SQL each screen runs, the columns a screen fetches but hides, and how tables join.

It only reads files. It never connects to, or changes, the Units database.
"""

__version__ = "1.0.0"
