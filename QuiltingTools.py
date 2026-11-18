"""Run the Quilting Tools desktop application."""

import argparse
import sqlite3
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from quilting.database import Database
from quilting.model import FieldError
from quilting.ui import Application


def main():
    parser = argparse.ArgumentParser(description="Quilting Tools - Fabric Inventory")
    parser.add_argument("--database", type=Path,
                        default=Path.home() / "QuiltingTools" / "QuiltingInventory.db")
    args = parser.parse_args()
    root = tk.Tk()
    root.withdraw()
    try:
        database = Database(args.database)
    except (sqlite3.Error, OSError, FieldError) as error:
        text = f"Database: Unable to open {args.database}.\n\n{error}\n\nNo upgrade was attempted."
        print(text, file=sys.stderr)
        messagebox.showerror("Quilting Tools - Startup Failed", text, parent=root)
        root.destroy()
        return 1
    try:
        try:
            Application(root, database)
        except (sqlite3.Error, OSError, FieldError) as error:
            messagebox.showerror("Quilting Tools - Startup Failed", str(error), parent=root)
            root.destroy()
            return 1
        root.deiconify()
        root.mainloop()
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
