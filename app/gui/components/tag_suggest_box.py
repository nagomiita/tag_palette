import tkinter as tk

import customtkinter as ctk


class TagSuggestBox(ctk.CTkEntry):
    def __init__(self, parent, suggestion_list, on_select=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.suggestion_list = suggestion_list
        self.on_select = on_select

        self.var = tk.StringVar()
        self.configure(textvariable=self.var)
        self.var.trace_add("write", self._on_change)  # ✅ trace → trace_add に更新

        self.popup = None

    def _on_change(self, *args):
        typed = self.var.get()
        matches = [s for s in self.suggestion_list if typed.lower() in s.name.lower()]
        self._show_suggestions(matches)

    def _show_suggestions(self, matches):
        if self.popup:
            self.popup.destroy()
            self.popup = None

        if not matches or not self.var.get():
            return

        # ✅ Toplevelを使ってポップアップ表示
        self.popup = tk.Toplevel(self)
        self.popup.wm_overrideredirect(True)  # 枠なし
        self.popup.attributes("-topmost", True)

        # 位置を画面上の絶対座標で指定
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        self.popup.geometry(f"+{x}+{y}")

        listbox = tk.Listbox(self.popup, height=min(6, len(matches)))
        listbox.pack()
        for match in matches:
            listbox.insert(tk.END, match.name)

        listbox.bind("<<ListboxSelect>>", lambda e: self._select_item(e, listbox))

    def _select_item(self, event, listbox):
        selection = listbox.get(listbox.curselection())
        self.var.set(selection)
        if self.on_select:
            self.on_select(selection)
        if self.popup:
            self.popup.destroy()
            self.popup = None
