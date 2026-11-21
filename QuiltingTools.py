"""Run the Quilting Tools desktop application."""

import argparse
import sqlite3
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from quilting.database import Database, UpgradeRequired
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
        try:
            database = Database(args.database)
        except UpgradeRequired:
            if not messagebox.askyesno(
                    "Database Upgrade Required",
                    "Close all other copies of Quilting Tools before continuing.\n\n"
                    "Upgrade dropdown, HelpText, ErrorMessage and Quilt Backs support and saved-plan selections, preserving "
                    "existing values? A verified PreUpgrade backup will be retained beside the "
                    "database. Existing fabric, history, IDs and selections will be preserved.\n\n"
                    "Upgrade now?", parent=root):
                root.destroy()
                return 0
            database = Database(args.database, upgrade=True)
            messagebox.showinfo("Database Upgrade Complete",
                                f"Backup retained at:\n{database.upgrade_backup}", parent=root)
    except (sqlite3.Error, OSError, FieldError) as error:
        text = (f"Database: Unable to open {args.database}.\n\n{error}\n\n"
                "Any uncommitted upgrade was rolled back. If an upgrade was started, "
                "retain the PreUpgrade backup beside the database.")
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
