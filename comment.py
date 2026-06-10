import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext


class TicketCommentApp:
    # Minimal color scheme
    BG_DARK = "#1a1a1a"
    BG_LIGHT = "#f5f5f5"
    TEXT_DARK = "#ffffff"
    TEXT_LIGHT = "#222222"
    ACCENT = "#2196F3"

    def __init__(self, root):
        self.root = root
        self.root.title("Ticket Comment Generator")
        self.root.geometry("950x700")
        self.root.configure(bg=self.BG_DARK)

        self.setup_styles()
        self.create_header()
        self.create_main_layout()
        self.fields = {}
        self.create_form()

    def setup_styles(self):
        """Configure ttk styles for minimal UI"""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "TCombobox", fieldbackground=self.BG_LIGHT, font=("Segoe UI", 9)
        )
        style.configure("TLabel", background=self.BG_LIGHT, font=("Segoe UI", 9))
        style.configure("TScrollbar", background=self.BG_DARK)

    def create_header(self):
        """Minimal header with buttons"""
        header = tk.Frame(self.root, bg=self.ACCENT, height=50)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        tk.Label(
            header,
            text="TICKET COMMENT GENERATOR",
            font=("Segoe UI", 13, "bold"),
            bg=self.ACCENT,
            fg=self.TEXT_DARK,
        ).pack(side=tk.LEFT, padx=15, pady=10)

        tk.Button(
            header,
            text="Generate",
            font=("Segoe UI", 10, "bold"),
            bg="#4CAF50",
            fg=self.TEXT_DARK,
            padx=12,
            pady=5,
            cursor="hand2",
            command=self.generate_comment,
        ).pack(side=tk.RIGHT, padx=5, pady=8)

        tk.Button(
            header,
            text="Copy",
            font=("Segoe UI", 10),
            bg="#FF9800",
            fg=self.TEXT_DARK,
            padx=12,
            pady=5,
            cursor="hand2",
            command=self.copy_to_clipboard,
        ).pack(side=tk.RIGHT, padx=5, pady=8)

        tk.Button(
            header,
            text="Clear",
            font=("Segoe UI", 10),
            bg="#f44336",
            fg=self.TEXT_DARK,
            padx=12,
            pady=5,
            cursor="hand2",
            command=self.clear_all,
        ).pack(side=tk.RIGHT, padx=5, pady=8)

    def create_main_layout(self):
        """Two-column layout: form on left, output on right"""
        main = tk.Frame(self.root, bg=self.BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # LEFT: Form
        left = tk.Frame(main, bg=self.BG_LIGHT)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 3))

        tk.Label(
            left,
            text="INPUT FORM",
            font=("Segoe UI", 10, "bold"),
            bg=self.BG_LIGHT,
            fg=self.TEXT_LIGHT,
        ).pack(anchor="w", padx=8, pady=(5, 0))

        # Scrollable form container
        canvas_form = tk.Canvas(left, bg=self.BG_LIGHT, highlightthickness=0)
        scrollbar_form = ttk.Scrollbar(
            left, orient="vertical", command=canvas_form.yview
        )
        self.form_frame = tk.Frame(canvas_form, bg=self.BG_LIGHT)

        self.form_frame.bind(
            "<Configure>",
            lambda e: canvas_form.configure(scrollregion=canvas_form.bbox("all")),
        )

        canvas_form.create_window((0, 0), window=self.form_frame, anchor="nw")
        canvas_form.configure(yscrollcommand=scrollbar_form.set)

        canvas_form.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar_form.pack(side=tk.RIGHT, fill=tk.Y)

        def on_form_scroll(event):
            canvas_form.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas_form.bind_all("<MouseWheel>", on_form_scroll)

        # RIGHT: Output
        right = tk.Frame(main, bg=self.BG_LIGHT)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(3, 0))

        tk.Label(
            right,
            text="OUTPUT TABLE",
            font=("Segoe UI", 10, "bold"),
            bg=self.BG_LIGHT,
            fg=self.TEXT_LIGHT,
        ).pack(anchor="w", padx=8, pady=(5, 0))

        table_frame = tk.Frame(right, bg=self.BG_LIGHT)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.tree = ttk.Treeview(
            table_frame, columns=("Field", "Value"), show="headings", height=20
        )
        self.tree.heading("Field", text="Field")
        self.tree.heading("Value", text="Value")
        self.tree.column("Field", width=180, anchor="w")
        self.tree.column("Value", width=280, anchor="w")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=vsb.set)

        # Color tags
        self.tree.tag_configure("pass", background="#c8e6c9")
        self.tree.tag_configure("fail", background="#ffcdd2")
        self.tree.tag_configure("block", background="#ffe0b2")

    def add_field(self, row, label_text, field_type="entry", values=None, default=""):
        """Helper to create form fields"""
        tk.Label(
            self.form_frame,
            text=label_text,
            font=("Segoe UI", 9, "bold"),
            bg=self.BG_LIGHT,
            fg=self.TEXT_LIGHT,
            anchor="w",
        ).grid(row=row, column=0, sticky="w", pady=4, padx=5)

        # Clean field name: lowercase, remove special chars
        field_name = (
            label_text.lower()
            .replace("(", "")
            .replace(")", "")
            .replace(".", "")
            .replace(",", "")
            .replace(" ", "_")
            .replace("/", "_")
        )

        if field_type == "combobox":
            widget = ttk.Combobox(
                self.form_frame,
                values=values,
                state="readonly",
                width=35,
                font=("Segoe UI", 9),
            )
            if default:
                widget.set(default)
            widget.grid(row=row, column=1, sticky="w", pady=4, padx=5)
            self.fields[field_name] = widget

        elif field_type == "listbox":
            frame = tk.Frame(self.form_frame, bg=self.BG_LIGHT)
            frame.grid(row=row, column=1, sticky="w", pady=4, padx=5)
            widget = tk.Listbox(
                frame,
                selectmode=tk.MULTIPLE,
                width=35,
                height=2,
                font=("Segoe UI", 9),
                bg=self.BG_LIGHT,
            )
            for val in values:
                widget.insert(tk.END, val)
            widget.pack(side=tk.LEFT)
            ttk.Scrollbar(frame, orient="vertical", command=widget.yview).pack(
                side=tk.RIGHT, fill=tk.Y
            )
            self.fields[field_name] = widget

        else:  # entry
            widget = tk.Entry(
                self.form_frame, width=38, font=("Segoe UI", 9), bg="white"
            )
            if default:
                widget.insert(0, default)
            widget.grid(row=row, column=1, sticky="w", pady=4, padx=5)
            self.fields[field_name] = widget

        return field_name

    def create_form(self):
        """Build form with minimal fields"""
        row = 0

        # Main fields
        self.add_field(
            row,
            "Verification Team",
            "combobox",
            ["OSV-DVT (Defect verification Test) Team"],
            "OSV-DVT (Defect verification Test) Team",
        )
        row += 1

        self.add_field(row, "Branch", "combobox", ["Dev", "RELEASE", "SPECIAL"], "Dev")
        row += 1

        self.add_field(row, "SW Build Version", "entry")
        row += 1

        test_result_field = self.add_field(
            row, "Test Result", "combobox", ["Pass", "Fail", "Blockfixing"], "Pass"
        )
        self.fields[test_result_field].bind(
            "<<ComboboxSelected>>", self.on_test_result_change
        )
        row += 1

        self.add_field(row, "Actual Behavior", "entry")
        row += 1

        self.add_field(row, "Vehicle Model/Variants", "entry")
        row += 1

        self.add_field(
            row,
            "Test Devices Used",
            "listbox",
            [
                "CANTOOL A1",
                "USB",
                "Mobile Android",
                "Canoe",
                "iPhone 15 Pro Max (iOS Version 17.4)",
            ],
        )
        row += 1

        self.add_field(row, "Frequency (e.g., 0/10)", "entry", default="0/10")
        row += 1

        self.add_field(row, "Impact Scenarios", "entry")
        row += 1

        # Conditional section
        sep = tk.Frame(self.form_frame, height=2, bg="#ddd")
        sep.grid(row=row, column=0, columnspan=2, sticky="ew", pady=8, padx=5)
        row += 1

        tk.Label(
            self.form_frame,
            text="CONDITIONAL",
            font=("Segoe UI", 8, "bold"),
            bg=self.BG_LIGHT,
            fg="#666",
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=5)
        row += 1

        # Pass field
        tk.Label(
            self.form_frame,
            text="Linked Test Cases (Pass)",
            font=("Segoe UI", 9),
            bg=self.BG_LIGHT,
            fg="#2e7d32",
        ).grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.pass_entry = tk.Entry(
            self.form_frame, width=38, font=("Segoe UI", 9), bg="#c8e6c9"
        )
        self.pass_entry.grid(row=row, column=1, sticky="w", pady=4, padx=5)
        row += 1

        # Fail field
        tk.Label(
            self.form_frame,
            text="Logs and Video (Fail)",
            font=("Segoe UI", 9),
            bg=self.BG_LIGHT,
            fg="#c62828",
        ).grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.fail_entry = tk.Entry(
            self.form_frame, width=38, font=("Segoe UI", 9), bg="#ffcdd2"
        )
        self.fail_entry.grid(row=row, column=1, sticky="w", pady=4, padx=5)

        self.update_conditional_fields("Pass")

    def update_conditional_fields(self, result):
        """Show/hide conditional fields"""
        if result == "Pass":
            self.pass_entry.grid()
            self.fail_entry.grid_remove()
        elif result == "Fail":
            self.pass_entry.grid_remove()
            self.fail_entry.grid()
        else:
            self.pass_entry.grid_remove()
            self.fail_entry.grid_remove()

    def on_test_result_change(self, event=None):
        self.update_conditional_fields(self.fields["test_result"].get())

    def get_selected_devices(self):
        """Get selected devices from listbox"""
        lb = self.fields["test_devices_used"]
        selected = [lb.get(i) for i in lb.curselection()]
        return ", ".join(selected) if selected else "NA"

    def build_rows(self):
        """Build output rows"""
        result = self.fields["test_result"].get()
        rows = [
            ("Verification Team", self.fields["verification_team"].get()),
            ("Dev Branch/Release branch", self.fields["branch"].get() + " branch"),
            ("SW build version", self.fields["sw_build_version"].get() or "NA"),
            ("Test Result", result),
            ("Actual Behavior", self.fields["actual_behavior"].get() or "NA"),
            (
                "Tested Vehicle model/Variants",
                self.fields["vehicle_model_variants"].get() or "NA",
            ),
            ("Test Devices Used", self.get_selected_devices()),
            (
                "Frequency of Issue Occurrences",
                self.fields["frequency_eg_0_10"].get() or "NA",
            ),
        ]

        if self.fields["impact_scenarios"].get().strip():
            rows.append(("Impact Scenarios", self.fields["impact_scenarios"].get()))

        if result == "Pass":
            linked = self.pass_entry.get().strip() or "NA"
            rows.append(("Linked Test Cases", linked))
        elif result == "Fail":
            logs_video = self.fail_entry.get().strip() or "NA"
            rows.append(("Logs and Video", logs_video))

        return rows, result

    def generate_comment(self):
        """Generate output"""
        rows, result = self.build_rows()

        # Clear and populate table
        for item in self.tree.get_children():
            self.tree.delete(item)

        tag = "pass" if result == "Pass" else "fail" if result == "Fail" else "block"

        for field, value in rows:
            self.tree.insert("", tk.END, values=(field, value), tags=(tag,))

    def copy_to_clipboard(self):
        """Copy table to clipboard as tab-separated"""
        rows = []
        for item in self.tree.get_children():
            vals = self.tree.item(item, "values")
            rows.append(f"{vals[0]}\t{vals[1]}")

        text = "\n".join(rows)
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            messagebox.showinfo(
                "Success", "Copied to clipboard!\nPaste in Excel as 2 columns."
            )
        else:
            messagebox.showwarning("Empty", "Generate a comment first!")

    def clear_all(self):
        """Clear all fields"""
        for item in self.tree.get_children():
            self.tree.delete(item)

        for key, widget in self.fields.items():
            if isinstance(widget, tk.Listbox):
                widget.selection_clear(0, tk.END)
            elif isinstance(widget, ttk.Combobox):
                if "verification" in key:
                    widget.set("OSV-DVT (Defect verification Test) Team")
                elif "branch" in key:
                    widget.set("Dev")
                elif "test_result" in key:
                    widget.set("Pass")
            else:
                widget.delete(0, tk.END)
                if "frequency" in key:
                    widget.insert(0, "0/10")

        self.pass_entry.delete(0, tk.END)
        self.fail_entry.delete(0, tk.END)
        self.update_conditional_fields("Pass")


if __name__ == "__main__":
    root = tk.Tk()
    app = TicketCommentApp(root)
    root.mainloop()
